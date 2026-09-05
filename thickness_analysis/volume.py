"""Cumulative track-volume calculation."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Iterable

import numpy as np

from .io import ThicknessRecord, read_thickness_records


@dataclass(frozen=True)
class VolumeRecord:
    track_id: int
    range_um: float
    cumulative_volume_um3: float


@dataclass(frozen=True)
class QualityCuts:
    minimum_contrast: float | None = None
    minimum_fit_r2: float | None = None
    maximum_fit_nrmse: float | None = None
    maximum_reduced_chi2: float | None = None
    minimum_fit_p_value: float | None = None
    maximum_width_error_nm: float | None = None
    maximum_width_relative_error: float | None = None
    maximum_width_nm: float | None = None

    @property
    def requested(self) -> bool:
        return any(value is not None for value in self.__dict__.values())


def passes_quality(row: ThicknessRecord, cuts: QualityCuts) -> bool:
    """Return whether a fitted width satisfies every requested cut."""

    if not math.isfinite(row.width_nm) or row.width_nm <= 0.0:
        return False

    checks = (
        (cuts.minimum_contrast, row.contrast, lambda value, limit: value >= limit),
        (cuts.minimum_fit_r2, row.fit_r2, lambda value, limit: value >= limit),
        (cuts.maximum_fit_nrmse, row.fit_nrmse, lambda value, limit: value <= limit),
        (
            cuts.maximum_reduced_chi2,
            row.reduced_chi2,
            lambda value, limit: value <= limit,
        ),
        (
            cuts.minimum_fit_p_value,
            row.fit_p_value,
            lambda value, limit: value >= limit,
        ),
        (
            cuts.maximum_width_error_nm,
            row.width_error_nm,
            lambda value, limit: value <= limit,
        ),
        (
            cuts.maximum_width_relative_error,
            row.width_relative_error,
            lambda value, limit: value <= limit,
        ),
        (cuts.maximum_width_nm, row.width_nm, lambda value, limit: value <= limit),
    )
    return all(
        limit is None or (math.isfinite(value) and predicate(value, limit))
        for limit, value, predicate in checks
    )


def calculate_volumes(
    records: Iterable[ThicknessRecord], maximum_width_nm: float | None = None
) -> list[VolumeRecord]:
    grouped: dict[int, list[ThicknessRecord]] = {}
    for row in records:
        grouped.setdefault(row.track_id, []).append(row)

    result: list[VolumeRecord] = []
    for track_id, rows in grouped.items():
        rows.sort(key=lambda row: row.distance_um)
        previous_distance = 0.0
        volume = 0.0
        for row in rows:
            interval_um = row.distance_um - previous_distance
            if interval_um < 0:
                raise ValueError(f"track {track_id} distances are not monotonic")
            previous_distance = row.distance_um
            if (
                not math.isfinite(row.width_nm)
                or row.width_nm <= 0.0
            ):
                continue

            if (
                maximum_width_nm is not None
                and row.width_nm > maximum_width_nm
            ):
                continue
            radius_um = row.width_nm / 2000.0
            volume += math.pi * radius_um**2 * interval_um
            result.append(VolumeRecord(track_id, row.distance_um, volume))
    return result


def calculate_volumes_with_quality(
    records: Iterable[ThicknessRecord],
    cuts: QualityCuts,
) -> list[VolumeRecord]:
    """Apply fit-quality cuts and interpolate rejected interior widths.

    A track needs at least two accepted points. Rejected widths between the
    first and last accepted measurements are reconstructed by linear
    interpolation. Leading/trailing rejected measurements are omitted; the
    first retained slice still spans range zero to the first accepted point,
    matching the historical cumulative-volume definition.
    """

    grouped: dict[int, list[ThicknessRecord]] = {}
    for row in records:
        grouped.setdefault(row.track_id, []).append(row)

    result: list[VolumeRecord] = []
    for track_id, rows in grouped.items():
        rows.sort(key=lambda row: row.distance_um)
        distances = np.array([row.distance_um for row in rows], dtype=float)
        widths = np.array([row.width_nm for row in rows], dtype=float)
        accepted = np.array([passes_quality(row, cuts) for row in rows], dtype=bool)
        if int(np.count_nonzero(accepted)) < 2:
            continue

        good_distances = distances[accepted]
        good_widths = widths[accepted]
        inside = (distances >= good_distances[0]) & (distances <= good_distances[-1])
        work_distances = distances[inside]
        work_widths = np.interp(work_distances, good_distances, good_widths)

        previous_distance = 0.0
        volume = 0.0
        for distance_um, width_nm in zip(work_distances, work_widths, strict=True):
            interval_um = float(distance_um - previous_distance)
            if interval_um < 0:
                raise ValueError(f"track {track_id} distances are not monotonic")
            previous_distance = float(distance_um)
            radius_um = float(width_nm) / 2000.0
            volume += math.pi * radius_um**2 * interval_um
            result.append(VolumeRecord(track_id, float(distance_um), volume))
    return result


def write_volume_records(path: str | Path, records: Iterable[VolumeRecord]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        stream.write("# columns: track_id range_um cumulative_volume_um3\n")
        for row in records:
            stream.write(
                f"{row.track_id} {row.range_um:.6f} "
                f"{row.cumulative_volume_um3:.9f}\n"
            )


def run_volume(
    input_path: str | Path,
    output_path: str | Path,
    maximum_width_nm: float | None = None,
    quality_cuts: QualityCuts | None = None,
) -> tuple[int, int]:
    source = read_thickness_records(input_path)
    cuts = quality_cuts or QualityCuts(maximum_width_nm=maximum_width_nm)
    if cuts.requested:
        result = calculate_volumes_with_quality(source, cuts)
    else:
        result = calculate_volumes(source)
    write_volume_records(output_path, result)
    return len(source), len(result)
