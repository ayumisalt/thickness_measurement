"""Cumulative track-volume calculation."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Iterable

from .io import ThicknessRecord, read_thickness_records


@dataclass(frozen=True)
class VolumeRecord:
    track_id: int
    range_um: float
    cumulative_volume_um3: float


def calculate_volumes(
    records: Iterable[ThicknessRecord], maximum_width_nm: float = 800.0
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
            if not (0.0 < row.width_nm <= maximum_width_nm):
                continue
            radius_um = row.width_nm / 2000.0
            volume += math.pi * radius_um**2 * interval_um
            result.append(VolumeRecord(track_id, row.distance_um, volume))
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
    maximum_width_nm: float = 800.0,
) -> tuple[int, int]:
    source = read_thickness_records(input_path)
    result = calculate_volumes(source, maximum_width_nm)
    write_volume_records(output_path, result)
    return len(source), len(result)
