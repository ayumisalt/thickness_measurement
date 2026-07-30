"""Combine thickness files while keeping track IDs globally unique."""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Iterable

from .io import ThicknessRecord, read_thickness_records, write_thickness_records


def resolve_inputs(specifications: Iterable[str]) -> list[Path]:
    resolved: list[Path] = []
    for specification in specifications:
        expanded = Path(specification).expanduser()
        if expanded.is_dir():
            matches = sorted(expanded.rglob("track_thickness.txt"))
        elif expanded.is_file():
            matches = [expanded]
        else:
            matches = [Path(item) for item in sorted(glob.glob(specification, recursive=True))]
        for path in matches:
            absolute = path.resolve()
            if absolute not in resolved:
                resolved.append(absolute)
    if not resolved:
        raise FileNotFoundError("no input thickness files matched")
    return resolved


def combine_results(
    input_paths: Iterable[Path], renumber: bool = True
) -> tuple[list[ThicknessRecord], list[str]]:
    combined: list[ThicknessRecord] = []
    source_map: list[str] = []
    next_track_id = 1
    for input_path in input_paths:
        records = read_thickness_records(input_path)
        ids = list(dict.fromkeys(record.track_id for record in records))
        mapping: dict[int, int] = {}
        for local_id in ids:
            global_id = next_track_id if renumber else local_id
            mapping[local_id] = global_id
            if renumber:
                next_track_id += 1
            source_map.append(f"source_map: {global_id} <- {input_path} track {local_id}")
        combined.extend(
            ThicknessRecord(
                track_id=mapping[row.track_id],
                distance_um=row.distance_um,
                resolution_nm=row.resolution_nm,
                width_nm=row.width_nm,
                sigma_nm=row.sigma_nm,
            )
            for row in records
        )
    return combined, source_map


def summarize(
    specifications: Iterable[str], output_path: str | Path, renumber: bool = True
) -> tuple[int, int]:
    paths = resolve_inputs(specifications)
    records, comments = combine_results(paths, renumber=renumber)
    write_thickness_records(output_path, records, comments)
    return len(paths), len(records)
