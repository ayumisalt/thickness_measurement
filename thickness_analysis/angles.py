"""Track inclination sidecars and z-reflection-symmetric reference selection."""

from __future__ import annotations

import math
from pathlib import Path
import re

import numpy as np

from .io import Track, load_tracks, read_thickness_records


def folded_theta(theta: float) -> float:
    if not math.isfinite(theta) or not 0 <= theta <= 180:
        raise ValueError("theta must be finite and between 0 and 180 degrees")
    return min(theta, 180.0 - theta)


def track_angles(track: Track) -> tuple[float, float, float]:
    """Endpoint polar theta plus min/max folded local segment inclinations."""
    xyz = np.array([(p.x_mm, p.y_mm, p.z_mm) for p in track.points])
    if len(xyz) < 2 or not np.all(np.isfinite(xyz)):
        raise ValueError(f"track {track.track_id}: invalid coordinates")

    def theta(delta: np.ndarray) -> float:
        if np.linalg.norm(delta) == 0:
            raise ValueError(f"track {track.track_id}: coincident endpoints")
        return math.degrees(math.atan2(math.hypot(delta[0], delta[1]), delta[2]))

    whole = theta(xyz[-1] - xyz[0])
    local = [folded_theta(theta(d)) for d in np.diff(xyz, axis=0) if np.linalg.norm(d) > 0]
    return whole, min(local), max(local)


def read_angles(path: str | Path) -> dict[int, float]:
    """Read whitespace columns track_id theta_deg; later diagnostic columns ignored."""
    result: dict[int, float] = {}
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            fields = line.split()
            track_id, theta = int(fields[0]), float(fields[1])
            folded_theta(theta)
            if track_id in result:
                raise ValueError(f"duplicate track {track_id}")
            result[track_id] = theta
        except (ValueError, IndexError) as exc:
            raise ValueError(f"{path}:{number}: invalid angle row: {exc}") from exc
    return result


def embedded_angles(records) -> dict[int, float]:
    """Require complete, consistent track angles in a thickness result."""
    result = {}
    for row in records:
        try:
            folded_theta(row.theta_deg)
        except ValueError as exc:
            raise ValueError(f"track {row.track_id}: missing/invalid embedded theta; regenerate thickness or provide an angle table") from exc
        if row.track_id in result and abs(result[row.track_id] - row.theta_deg) > 1e-7:
            raise ValueError(f"track {row.track_id}: inconsistent embedded theta")
        result[row.track_id] = row.theta_deg
    return result


def select_reference_ids(
    reference_ids: set[int], reference_angles: dict[int, float],
    candidate_ids: set[int], candidate_angles: dict[int, float],
    window_deg: float,
) -> tuple[set[int], float]:
    if not math.isfinite(window_deg) or not 0 <= window_deg <= 90:
        raise ValueError("theta window must be finite and between 0 and 90 degrees")
    if len(candidate_ids) != 1:
        raise ValueError("theta matching requires exactly one candidate track")
    missing = reference_ids - reference_angles.keys()
    if missing:
        raise ValueError(f"missing reference angles for track IDs {sorted(missing)}")
    candidate_id = next(iter(candidate_ids))
    if candidate_id not in candidate_angles:
        raise ValueError(f"missing candidate angle for track {candidate_id}")
    center = folded_theta(candidate_angles[candidate_id])
    selected = {i for i in reference_ids
                if abs(folded_theta(reference_angles[i]) - center) <= window_deg + 1e-10}
    return selected, center


def build_angle_table(input_path: str | Path, path_maps: list[tuple[Path, Path]]):
    """Follow nested source_map comments to the exact measurement track coordinates.

    Prefix mappings are explicit, longest-first, to relocate server provenance.
    Missing/ambiguous provenance is an error, never a silently dropped track.
    """
    records = read_thickness_records(input_path)
    if records and all(math.isfinite(r.theta_deg) for r in records):
        angles = embedded_angles(records)
        rows = []
        for track_id, theta in angles.items():
            local = [folded_theta(r.local_theta_deg) for r in records
                     if r.track_id == track_id and math.isfinite(r.local_theta_deg)]
            rows.append((track_id, theta, folded_theta(theta), min(local) if local else float('nan'),
                         max(local) if local else float('nan'), str(Path(input_path).resolve()), track_id, None))
        return rows

    def relocate(path: Path) -> Path:
        for old, new in sorted(path_maps, key=lambda pair: len(str(pair[0])), reverse=True):
            if path.is_relative_to(old):
                return new / path.relative_to(old)
        return path

    cache = {}
    def metadata(path: Path):
        if path not in cache:
            mapping, headers = {}, {}
            for line in path.read_text().splitlines():
                match = re.match(r"# source_map: (\d+) <- (.*) track (\d+)$", line)
                if match:
                    key = int(match[1])
                    if key in mapping:
                        raise ValueError(f"duplicate source mapping: {path} track {key}")
                    mapping[key] = (match[2], int(match[3]))
                elif line.startswith("# ") and ":" in line:
                    key, value = line[2:].split(":", 1)
                    headers[key] = value.strip()
            cache[path] = mapping, headers
        return cache[path]

    def resolve(path: Path, track_id: int, seen: set):
        key = (path.resolve(), track_id)
        if key in seen:
            raise ValueError(f"source mapping cycle: {key}")
        mapping, headers = metadata(path)
        if mapping:
            if track_id not in mapping:
                raise ValueError(f"missing source mapping: {key}")
            name, local_id = mapping[track_id]
            source = Path(name)
            if not source.is_absolute():
                source = path.parent / source
            return resolve(relocate(source), local_id, seen | {key})
        if "tracks" not in headers or "input_shrink" not in headers:
            raise ValueError(f"missing tracks/input_shrink provenance: {path}")
        coords = Path(headers["tracks"])
        if not coords.is_absolute():
            coords = path.parent / coords
        coords = relocate(coords)
        shrink = float(headers["input_shrink"])
        if not math.isfinite(shrink) or shrink <= 0:
            raise ValueError(f"invalid measurement shrink: {path}")
        tracks, _ = load_tracks(coords, shrink_override=shrink)
        matches = [t for t in tracks if t.track_id == track_id]
        if len(matches) != 1:
            raise ValueError(f"missing coordinate track {track_id}: {coords}")
        return matches[0], coords, shrink

    rows = []
    for track_id in dict.fromkeys(r.track_id for r in read_thickness_records(input_path)):
        track, coords, shrink = resolve(Path(input_path).resolve(), track_id, set())
        theta, low, high = track_angles(track)
        rows.append((track_id, theta, folded_theta(theta), low, high, str(coords), track.track_id, shrink))
    return rows
