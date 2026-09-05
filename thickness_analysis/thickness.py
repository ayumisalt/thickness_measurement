"""Track-thickness measurement from a microscope z-stack."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
from scipy.optimize import brentq, curve_fit
from scipy.stats import chi2

from .io import ImageStack, ThicknessRecord, Track


@dataclass(frozen=True)
class ThicknessConfig:
    spacing_um: float = 1.0
    endpoint_margin_um: float = 2.0
    transverse_half_width_um: float = 2.0
    focus_search_frames: int = 25
    focus_window_px: int = 15
    gaussian_kernel_px: int = 101
    minimum_contrast: float = 50.0


@dataclass(frozen=True)
class ProfileFit:
    resolution_nm: float
    width_nm: float
    sigma_nm: float

    contrast: float
    fit_r2: float
    fit_nrmse: float
    reduced_chi2: float
    fit_p_value: float

    width_error_nm: float
    width_relative_error: float
    noise_sigma: float


@dataclass(frozen=True)
class _Polyline:
    points_mm: np.ndarray
    segment_vectors_mm: np.ndarray
    segment_lengths_um: np.ndarray
    cumulative_lengths_um: np.ndarray

    @classmethod
    def from_track(cls, track: Track) -> "_Polyline":
        points = np.array(
            [[point.x_mm, point.y_mm, point.z_mm] for point in track.points],
            dtype=float,
        )
        vectors = np.diff(points, axis=0)
        lengths_um = np.linalg.norm(vectors, axis=1) * 1000.0
        nonzero = lengths_um > 1e-12
        if not np.any(nonzero):
            raise ValueError(f"track {track.track_id} has zero 3D length")

        # Remove consecutive duplicate points without changing the polyline.
        points = points[np.concatenate(([True], nonzero))]
        vectors = np.diff(points, axis=0)
        lengths_um = np.linalg.norm(vectors, axis=1) * 1000.0
        cumulative = np.concatenate(([0.0], np.cumsum(lengths_um)))
        return cls(points, vectors, lengths_um, cumulative)

    @property
    def length_um(self) -> float:
        return float(self.cumulative_lengths_um[-1])

    def sample(self, distance_um: float) -> tuple[np.ndarray, np.ndarray]:
        """Return the point and local XY unit tangent at an arc distance."""

        segment = int(
            np.searchsorted(self.cumulative_lengths_um[1:], distance_um, side="left")
        )
        segment = min(segment, len(self.segment_lengths_um) - 1)
        within_um = distance_um - self.cumulative_lengths_um[segment]
        fraction = within_um / self.segment_lengths_um[segment]
        point = self.points_mm[segment] + fraction * self.segment_vectors_mm[segment]

        xy = self.segment_vectors_mm[segment, :2]
        xy_length = float(np.linalg.norm(xy))
        if xy_length <= 1e-15:
            candidates = np.flatnonzero(
                np.linalg.norm(self.segment_vectors_mm[:, :2], axis=1) > 1e-15
            )
            if not len(candidates):
                raise ValueError("track has no measurable XY projection")
            nearest = int(candidates[np.argmin(np.abs(candidates - segment))])
            xy = self.segment_vectors_mm[nearest, :2]
            xy_length = float(np.linalg.norm(xy))
        return point, xy / xy_length

def tanh_gaussian(
    x_nm: np.ndarray,
    saturation: float,
    center_nm: float,
    sigma_nm: float,
    height: float,
) -> np.ndarray:
    gaussian = saturation * np.exp(
        -((x_nm - center_nm) ** 2) / (2.0 * sigma_nm**2)
    )
    return height * np.tanh(gaussian)


def edge_resolution_nm(saturation: float, sigma_nm: float) -> float:
    """Mean 10--90 % edge distance of the symmetric fitted profile."""

    peak_tanh = math.tanh(saturation)

    def radius(fraction: float) -> float:
        target = math.atanh(fraction * peak_tanh)
        return sigma_nm * math.sqrt(2.0 * math.log(saturation / target))

    return radius(0.10) - radius(0.90)


def inflection_width_nm(saturation: float, sigma_nm: float) -> float:
    """Distance between the two inflection points of the fitted profile."""

    def equation(radius_nm: float) -> float:
        u = saturation * math.exp(-(radius_nm**2) / (2.0 * sigma_nm**2))
        return radius_nm**2 * (1.0 - 2.0 * u * math.tanh(u)) - sigma_nm**2

    upper = max(10.0, 10.0 * sigma_nm)
    root = brentq(equation, 0.0, upper)
    return 2.0 * root

def _width_uncertainty_nm(
    params: np.ndarray,
    pcov: np.ndarray,
) -> float:

    saturation = float(params[0])
    sigma_nm = float(params[2])

    # We need covariance for saturation and sigma.
    cov = pcov[np.ix_([0, 2], [0, 2])]

    if not np.all(np.isfinite(cov)):
        return float("inf")

    # Numerical derivatives of width(saturation, sigma).
    ds = max(abs(saturation) * 1e-5, 1e-6)
    d_sigma = max(abs(sigma_nm) * 1e-5, 1e-3)

    try:
        dw_ds = (
            inflection_width_nm(
                saturation + ds,
                sigma_nm,
            )
            - inflection_width_nm(
                saturation - ds,
                sigma_nm,
            )
        ) / (2.0 * ds)

        dw_dsigma = (
            inflection_width_nm(
                saturation,
                sigma_nm + d_sigma,
            )
            - inflection_width_nm(
                saturation,
                sigma_nm - d_sigma,
            )
        ) / (2.0 * d_sigma)

    except (ValueError, OverflowError):
        return float("inf")

    gradient = np.array(
        [dw_ds, dw_dsigma],
        dtype=float,
    )

    variance = float(
        gradient @ cov @ gradient
    )

    if not np.isfinite(variance) or variance < 0:
        return float("inf")

    return math.sqrt(variance)


def _estimate_noise_sigma(
    brightness: np.ndarray,
    background_samples: np.ndarray | None = None,
) -> float:
    """Estimate background noise from the outer quarters of a profile."""

    if background_samples is None:
        tail_size = max(2, int(math.ceil(len(brightness) * 0.25)))
        tails = np.concatenate((brightness[:tail_size], brightness[-tail_size:]))
    else:
        tails = np.asarray(background_samples, dtype=float).ravel()
    median = float(np.median(tails))
    centered = tails - median
    mad_sigma = 1.4826 * float(np.median(np.abs(centered)))
    # cv2.subtract clips negative DoG fluctuations to zero. For a clipped,
    # zero-mean Gaussian, E[max(0, X)^2] = sigma^2 / 2.
    clipped_rms_sigma = math.sqrt(2.0 * float(np.mean(centered**2)))
    sigma = max(mad_sigma, clipped_rms_sigma)
    return max(sigma, 1.0)

def _fit_profile(
    coordinates_nm: np.ndarray,
    brightness: np.ndarray,
    background_samples: np.ndarray | None = None,
) -> ProfileFit | None:

    contrast = float(np.ptp(brightness))

    if not np.isfinite(contrast) or contrast <= 0:
        return None

    center_guess = float(
        coordinates_nm[int(np.argmax(brightness))]
    )

    p0 = [
        1.0,
        center_guess,
        200.0,
        max(float(np.max(brightness)), 1.0),
    ]

    half_range = float(
        max(
            abs(coordinates_nm[0]),
            abs(coordinates_nm[-1]),
        )
    )

    # Estimate uncertainty from background samples rather than imposing a
    # fixed value. This keeps chi-square probabilities data-dependent.
    noise_sigma = _estimate_noise_sigma(brightness, background_samples)

    try:
        params, pcov = curve_fit(
            tanh_gaussian,
            coordinates_nm,
            brightness,
            p0=p0,
            bounds=(
                [0.01, -half_range, 10.0, 0.1],
                [10.0, half_range, 2000.0, 1000.0],
            ),
            sigma=np.full_like(
                brightness,
                noise_sigma,
                dtype=float,
            ),
            absolute_sigma=True,
            maxfev=20_000,
        )

        saturation, _, sigma_nm, _ = map(
            float,
            params,
        )

        resolution_nm = edge_resolution_nm(
            saturation,
            sigma_nm,
        )

        width_nm = inflection_width_nm(
            saturation,
            sigma_nm,
        )

        fitted = tanh_gaussian(
            coordinates_nm,
            *params,
        )

        residuals = brightness - fitted

        # -------------------------------------------------
        # RMSE / normalized RMSE
        # -------------------------------------------------
        rmse = float(
            np.sqrt(
                np.mean(residuals**2)
            )
        )

        fit_nrmse = (
            rmse / contrast
            if contrast > 0
            else float("inf")
        )

        # -------------------------------------------------
        # R^2
        # -------------------------------------------------
        ss_res = float(
            np.sum(residuals**2)
        )

        ss_tot = float(
            np.sum(
                (
                    brightness
                    - np.mean(brightness)
                ) ** 2
            )
        )

        fit_r2 = (
            1.0 - ss_res / ss_tot
            if ss_tot > 0
            else float("nan")
        )

        # -------------------------------------------------
        # chi-square
        #
        # The noise estimate comes from the profile tails, independently of
        # the fitted residuals.
        # -------------------------------------------------
        chi2_value = float(
            np.sum(
                (residuals / noise_sigma) ** 2
            )
        )

        dof = len(brightness) - len(params)

        if dof > 0:
            reduced_chi2 = chi2_value / dof
            fit_p_value = float(
                chi2.sf(
                    chi2_value,
                    dof,
                )
            )
        else:
            reduced_chi2 = float("nan")
            fit_p_value = float("nan")

        # -------------------------------------------------
        # Width uncertainty propagated from curve_fit
        # covariance.
        # -------------------------------------------------
        width_error_nm = _width_uncertainty_nm(
            params,
            pcov,
        )

        if (
            width_nm > 0
            and np.isfinite(width_error_nm)
        ):
            width_relative_error = (
                width_error_nm / width_nm
            )
        else:
            width_relative_error = float("inf")

        return ProfileFit(
            resolution_nm=resolution_nm,
            width_nm=width_nm,
            sigma_nm=sigma_nm,
            contrast=contrast,
            fit_r2=fit_r2,
            fit_nrmse=fit_nrmse,
            reduced_chi2=reduced_chi2,
            fit_p_value=fit_p_value,
            width_error_nm=width_error_nm,
            width_relative_error=width_relative_error,
            noise_sigma=noise_sigma,
        )

    except (
        RuntimeError,
        ValueError,
        OverflowError,
    ):
        return None


class _TrackImageCache:
    def __init__(
        self,
        stack: ImageStack,
        track_points_px: np.ndarray,
        config: ThicknessConfig,
    ) -> None:
        pixel_um = stack.nominal_pixel_size_um
        gaussian_radius = config.gaussian_kernel_px // 2
        margin = int(
            math.ceil(
                max(
                    config.transverse_half_width_um / pixel_um,
                    config.focus_window_px,
                )
                + gaussian_radius
                + 4
            )
        )
        x0 = max(0, math.floor(float(np.min(track_points_px[:, 0]))) - margin)
        y0 = max(0, math.floor(float(np.min(track_points_px[:, 1]))) - margin)
        x1 = min(
            stack.width,
            math.ceil(float(np.max(track_points_px[:, 0]))) + margin + 1,
        )
        y1 = min(
            stack.height,
            math.ceil(float(np.max(track_points_px[:, 1]))) + margin + 1,
        )
        self.stack = stack
        self.x0 = x0
        self.y0 = y0
        self.x1 = x1
        self.y1 = y1
        self.kernel = config.gaussian_kernel_px

    @lru_cache(maxsize=None)
    def dog(self, frame_index: int) -> np.ndarray:
        frame = self.stack.frames[frame_index]
        image = cv2.imread(str(frame.path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise FileNotFoundError(f"could not read microscope image: {frame.path}")
        crop = image[self.y0 : self.y1, self.x0 : self.x1]
        background = cv2.GaussianBlur(crop, (self.kernel, self.kernel), 0)
        return cv2.subtract(background, crop)

    def local_point(self, point_px: np.ndarray) -> np.ndarray:
        return point_px - np.array([self.x0, self.y0], dtype=float)


def _sample_profile(
    image: np.ndarray,
    stack: ImageStack,
    point_stage: np.ndarray,
    direction_stage: np.ndarray,
    perpendicular_stage: np.ndarray,
    config: ThicknessConfig,
    cache: _TrackImageCache,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    step_um = stack.nominal_pixel_size_um
    offsets_um = np.arange(
        -config.transverse_half_width_um,
        config.transverse_half_width_um + 0.5 * step_um,
        step_um,
    )
    longitudinal_offsets_um = np.linspace(-0.5, 0.5, 5)
    stage_points = (
        point_stage[:, None, None]
        + direction_stage[:, None, None]
        * longitudinal_offsets_um[None, :, None]
        / 1000.0
        + perpendicular_stage[:, None, None]
        * offsets_um[None, None, :]
        / 1000.0
    )
    pixels = np.column_stack(
        [
            stack.stage_to_pixel(float(x), float(y))
            for x, y in stage_points.reshape(2, -1).T
        ]
    ).T.reshape(len(longitudinal_offsets_um), len(offsets_um), 2)
    local = pixels - np.array([cache.x0, cache.y0], dtype=float)
    map_x = local[:, :, 0].astype(np.float32)
    map_y = local[:, :, 1].astype(np.float32)
    sampled = cv2.remap(
        image,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101,
    ).astype(float)
    center_profile = sampled[len(longitudinal_offsets_um) // 2]
    tail_size = max(2, int(math.ceil(len(offsets_um) * 0.25)))
    neighboring_profiles = np.delete(
        sampled, len(longitudinal_offsets_um) // 2, axis=0
    )
    background = np.concatenate(
        (
            neighboring_profiles[:, :tail_size].ravel(),
            neighboring_profiles[:, -tail_size:].ravel(),
        )
    )
    return offsets_um * 1000.0, center_profile, background


def measure_track(
    stack: ImageStack,
    track: Track,
    config: ThicknessConfig = ThicknessConfig(),
) -> list[ThicknessRecord]:
    polyline = _Polyline.from_track(track)
    length_3d_um = polyline.length_um

    if length_3d_um <= 2.0 * config.endpoint_margin_um:
        raise ValueError(
            f"track {track.track_id} is only "
            f"{length_3d_um:.3f} um long in 3D; "
            "reduce endpoint margin"
        )

    track_points_px = np.array(
        [stack.stage_to_pixel(point[0], point[1]) for point in polyline.points_mm]
    )

    cache = _TrackImageCache(
        stack,
        track_points_px,
        config,
    )

    z_values = np.array(
        [frame.z_mm for frame in stack.frames]
    )

    # ---------------------------------------------------------
    # Sampling is now defined along the TRUE 3D track length.
    #
    # spacing_um = 1 means 1 um intervals in physical 3D space.
    # endpoint_margin_um = 2 means 2 um from each physical endpoint.
    # ---------------------------------------------------------
    distances = np.arange(
        config.endpoint_margin_um,
        length_3d_um - config.endpoint_margin_um + 1e-9,
        config.spacing_um,
    )

    records: list[ThicknessRecord] = []

    for distance_um in distances:
        point_3d, direction_xy = polyline.sample(float(distance_um))
        point_stage = point_3d[:2]
        perpendicular = np.array([-direction_xy[1], direction_xy[0]])

        point_px = stack.stage_to_pixel(*point_stage)
        local_px = cache.local_point(point_px)

        predicted_z = float(point_3d[2])

        center_index = int(
            np.argmin(np.abs(z_values - predicted_z))
        )
        lo = max(0, center_index - config.focus_search_frames)
        hi = min(len(stack.frames), center_index + config.focus_search_frames + 1)

        best_index = -1
        best_focus = -math.inf
        for frame_index in range(lo, hi):
            dog = cache.dog(frame_index)
            x = int(round(local_px[0]))
            y = int(round(local_px[1]))
            radius = config.focus_window_px
            patch = dog[
                max(0, y - radius) : min(dog.shape[0], y + radius),
                max(0, x - radius) : min(dog.shape[1], x + radius),
            ]
            score = float(np.sum(patch, dtype=np.float64))
            if score > best_focus:
                best_focus = score
                best_index = frame_index

        coordinates_nm, brightness, background = _sample_profile(
            cache.dog(best_index),
            stack,
            point_stage,
            direction_xy,
            perpendicular,
            config,
            cache,
        )
        if float(np.ptp(brightness)) < config.minimum_contrast:
            continue
        fit = _fit_profile(coordinates_nm, brightness, background)
        if fit is None:
            continue
        # resolution_nm, width_nm, sigma_nm = fit
        records.append(
            ThicknessRecord(
                track_id=track.track_id,
                distance_um=float(distance_um),

                resolution_nm=fit.resolution_nm,
                width_nm=fit.width_nm,
                sigma_nm=fit.sigma_nm,

                contrast=fit.contrast,
                fit_r2=fit.fit_r2,
                fit_nrmse=fit.fit_nrmse,
                reduced_chi2=fit.reduced_chi2,
                fit_p_value=fit.fit_p_value,
                width_error_nm=fit.width_error_nm,
                width_relative_error=fit.width_relative_error,
                noise_sigma=fit.noise_sigma,
            )
        )
    return records


def measure_tracks(
    stack: ImageStack,
    tracks: Iterable[Track],
    config: ThicknessConfig = ThicknessConfig(),
) -> list[ThicknessRecord]:
    records: list[ThicknessRecord] = []
    for track in tracks:
        records.extend(measure_track(stack, track, config))
    return records
