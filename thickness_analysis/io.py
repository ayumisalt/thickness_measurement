"""Input/output helpers shared by the analysis commands."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class TrackPoint:
    """A point in stage coordinates (millimetres)."""

    x_mm: float
    y_mm: float
    z_mm: float


@dataclass(frozen=True)
class Track:
    track_id: int
    points: tuple[TrackPoint, ...]

    @property
    def endpoints(self) -> tuple[TrackPoint, TrackPoint]:
        if len(self.points) < 2:
            raise ValueError(f"track {self.track_id} has fewer than two points")
        return self.points[0], self.points[-1]


@dataclass(frozen=True)
class ImageFrame:
    path: Path
    z_mm: float


@dataclass(frozen=True)
class ImageStack:
    json_path: Path
    width: int
    height: int
    pixel_to_stage: np.ndarray
    origin_x_mm: float
    origin_y_mm: float
    frames: tuple[ImageFrame, ...]

    def stage_to_pixel(self, x_mm: float, y_mm: float) -> np.ndarray:
        offset = np.array(
            [x_mm - self.origin_x_mm, y_mm - self.origin_y_mm], dtype=float
        )
        return np.linalg.solve(self.pixel_to_stage, offset) + np.array(
            [self.width / 2.0, self.height / 2.0]
        )

    @property
    def nominal_pixel_size_um(self) -> float:
        # sqrt(area) is stable for a rotated (and mildly anisotropic) affine matrix.
        return float(np.sqrt(abs(np.linalg.det(self.pixel_to_stage))) * 1000.0)


_SHRINK_RE = re.compile(
    r"^\s*#\s*Shrink\s*:\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))", re.IGNORECASE
)


def load_image_stack(json_path: str | Path) -> ImageStack:
    path = Path(json_path).expanduser().resolve()
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)

    image_type = data["ImageType"]
    affine = data["AffineP2S"]
    if len(affine) < 4:
        raise ValueError("AffineP2S must contain at least four values")
    matrix = np.array([[affine[0], affine[1]], [affine[2], affine[3]]])
    if abs(np.linalg.det(matrix)) < 1e-15:
        raise ValueError("AffineP2S is singular")

    images = data.get("Images", [])
    if not images:
        raise ValueError(f"{path} contains no Images")
    base = path.parent
    frames = tuple(
        ImageFrame(path=(base / item["Path"]).resolve(), z_mm=float(item["z"]))
        for item in images
    )
    return ImageStack(
        json_path=path,
        width=int(image_type["Width"]),
        height=int(image_type["Height"]),
        pixel_to_stage=matrix,
        origin_x_mm=float(images[0]["x"]),
        origin_y_mm=float(images[0]["y"]),
        frames=frames,
    )


def load_tracks(
    track_path: str | Path, shrink_override: float | None = None
) -> tuple[list[Track], float]:
    """Read either Uguis four-column or fitting five-column track text.

    Four columns are ``track_id x y z``. Five columns are
    ``event_id track_id x y z``. Coordinates are converted back to acquisition
    stage z using the ``# Shrink`` header (or an explicit override).
    """

    path = Path(track_path).expanduser().resolve()
    shrink = 1.0
    rows: list[tuple[int, float, float, float]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, raw in enumerate(stream, start=1):
            match = _SHRINK_RE.match(raw)
            if match:
                shrink = float(match.group(1))
                continue
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = stripped.split()
            try:
                if len(fields) == 4:
                    track_id = int(fields[0])
                    x, y, z = map(float, fields[1:4])
                elif len(fields) >= 5:
                    track_id = int(fields[1])
                    x, y, z = map(float, fields[2:5])
                else:
                    raise ValueError("expected four or five columns")
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
            rows.append((track_id, x, y, z))

    if shrink_override is not None:
        shrink = shrink_override
    if shrink <= 0:
        raise ValueError("Shrink must be positive")

    grouped: dict[int, list[TrackPoint]] = {}
    for track_id, x, y, z in rows:
        grouped.setdefault(track_id, []).append(TrackPoint(x, y, z / shrink))
    tracks = [Track(track_id, tuple(points)) for track_id, points in grouped.items()]
    if not tracks:
        raise ValueError(f"{path} contains no track coordinates")
    bad = [track.track_id for track in tracks if len(track.points) < 2]
    if bad:
        raise ValueError(f"tracks with fewer than two points: {bad}")
    return tracks, shrink


@dataclass(frozen=True)
class ThicknessRecord:
    track_id: int
    distance_um: float
    resolution_nm: float
    width_nm: float
    sigma_nm: float


def read_thickness_records(path: str | Path) -> list[ThicknessRecord]:
    records: list[ThicknessRecord] = []
    input_path = Path(path)
    with input_path.open(encoding="utf-8") as stream:
        for line_number, raw in enumerate(stream, start=1):
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = stripped.split()
            if len(fields) < 5:
                raise ValueError(
                    f"{input_path}:{line_number}: expected at least five columns"
                )
            try:
                records.append(
                    ThicknessRecord(
                        track_id=int(fields[0]),
                        distance_um=float(fields[1]),
                        resolution_nm=float(fields[2]),
                        width_nm=float(fields[3]),
                        sigma_nm=float(fields[4]),
                    )
                )
            except ValueError as exc:
                raise ValueError(f"{input_path}:{line_number}: {exc}") from exc
    return records


def write_thickness_records(
    path: str | Path,
    records: Iterable[ThicknessRecord],
    comments: Iterable[str] = (),
) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as stream:
        stream.write("# columns: track_id distance_um resolution_nm width_nm sigma_nm\n")
        for comment in comments:
            stream.write(f"# {comment}\n")
        for row in records:
            stream.write(
                f"{row.track_id} {row.distance_um:.6f} "
                f"{row.resolution_nm:.6f} {row.width_nm:.6f} "
                f"{row.sigma_nm:.6f}\n"
            )
