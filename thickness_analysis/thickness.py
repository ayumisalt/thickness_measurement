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


def _fit_profile(
    coordinates_nm: np.ndarray, brightness: np.ndarray
) -> tuple[float, float, float] | None:
    contrast = float(np.ptp(brightness))
    if not np.isfinite(contrast) or contrast <= 0:
        return None
    center_guess = float(coordinates_nm[int(np.argmax(brightness))])
    p0 = [1.0, center_guess, 200.0, max(float(np.max(brightness)), 1.0)]
    half_range = float(max(abs(coordinates_nm[0]), abs(coordinates_nm[-1])))
    try:
        params, _ = curve_fit(
            tanh_gaussian,
            coordinates_nm,
            brightness,
            p0=p0,
            bounds=(
                [0.01, -half_range, 10.0, 0.1],
                [10.0, half_range, 2000.0, 1000.0],
            ),
            sigma=np.full_like(brightness, 20.0, dtype=float),
            absolute_sigma=True,
            maxfev=20_000,
        )
        saturation, _, sigma_nm, _ = map(float, params)
        return (
            edge_resolution_nm(saturation, sigma_nm),
            inflection_width_nm(saturation, sigma_nm),
            sigma_nm,
        )
    except (RuntimeError, ValueError, OverflowError):
        return None


class _TrackImageCache:
    def __init__(
        self,
        stack: ImageStack,
        start_px: np.ndarray,
        end_px: np.ndarray,
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
        x0 = max(0, math.floor(min(start_px[0], end_px[0])) - margin)
        y0 = max(0, math.floor(min(start_px[1], end_px[1])) - margin)
        x1 = min(stack.width, math.ceil(max(start_px[0], end_px[0])) + margin + 1)
        y1 = min(stack.height, math.ceil(max(start_px[1], end_px[1])) + margin + 1)
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
    perpendicular_stage: np.ndarray,
    config: ThicknessConfig,
    cache: _TrackImageCache,
) -> tuple[np.ndarray, np.ndarray]:
    step_um = stack.nominal_pixel_size_um
    offsets_um = np.arange(
        -config.transverse_half_width_um,
        config.transverse_half_width_um + 0.5 * step_um,
        step_um,
    )
    stage_points = point_stage[:, None] + (
        perpendicular_stage[:, None] * offsets_um[None, :] / 1000.0
    )
    pixels = np.column_stack(
        [
            stack.stage_to_pixel(float(x), float(y))
            for x, y in stage_points.T
        ]
    ).T
    local = pixels - np.array([cache.x0, cache.y0], dtype=float)
    map_x = local[:, 0].astype(np.float32).reshape(1, -1)
    map_y = local[:, 1].astype(np.float32).reshape(1, -1)
    sampled = cv2.remap(
        image,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101,
    ).ravel()
    return offsets_um * 1000.0, sampled.astype(float)


def measure_track(
    stack: ImageStack, track: Track, config: ThicknessConfig = ThicknessConfig()
) -> list[ThicknessRecord]:
    start, end = track.endpoints
    start_stage = np.array([start.x_mm, start.y_mm], dtype=float)
    end_stage = np.array([end.x_mm, end.y_mm], dtype=float)
    delta_stage = end_stage - start_stage
    length_mm = float(np.linalg.norm(delta_stage))
    length_um = length_mm * 1000.0
    if length_um <= 2.0 * config.endpoint_margin_um:
        raise ValueError(
            f"track {track.track_id} is only {length_um:.3f} um long; "
            "reduce endpoint margin"
        )
    direction = delta_stage / length_mm
    perpendicular = np.array([-direction[1], direction[0]])
    start_px = stack.stage_to_pixel(*start_stage)
    end_px = stack.stage_to_pixel(*end_stage)
    cache = _TrackImageCache(stack, start_px, end_px, config)
    z_values = np.array([frame.z_mm for frame in stack.frames])

    distances = np.arange(
        config.endpoint_margin_um,
        length_um - config.endpoint_margin_um + 1e-9,
        config.spacing_um,
    )
    records: list[ThicknessRecord] = []
    for distance_um in distances:
        fraction = distance_um / length_um
        point_stage = start_stage + fraction * delta_stage
        point_px = stack.stage_to_pixel(*point_stage)
        local_px = cache.local_point(point_px)
        predicted_z = start.z_mm + fraction * (end.z_mm - start.z_mm)
        center_index = int(np.argmin(np.abs(z_values - predicted_z)))
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

        coordinates_nm, brightness = _sample_profile(
            cache.dog(best_index),
            stack,
            point_stage,
            perpendicular,
            config,
            cache,
        )
        if float(np.ptp(brightness)) < config.minimum_contrast:
            continue
        fit = _fit_profile(coordinates_nm, brightness)
        if fit is None:
            continue
        resolution_nm, width_nm, sigma_nm = fit
        records.append(
            ThicknessRecord(
                track_id=track.track_id,
                distance_um=float(distance_um),
                resolution_nm=resolution_nm,
                width_nm=width_nm,
                sigma_nm=sigma_nm,
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
