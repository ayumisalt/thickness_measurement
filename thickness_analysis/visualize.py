"""Volume--range plotting and reference-band comparison."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .volume import VolumeRecord


def read_volume_records(path: str | Path) -> list[VolumeRecord]:
    records: list[VolumeRecord] = []
    input_path = Path(path)
    with input_path.open(encoding="utf-8") as stream:
        for line_number, raw in enumerate(stream, start=1):
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = stripped.split()
            try:
                if len(fields) >= 3:
                    track_id = int(fields[0])
                    range_um = float(fields[1])
                    volume_um3 = float(fields[2])
                elif len(fields) == 2:  # legacy output had no track ID
                    track_id = 1
                    range_um = float(fields[0])
                    volume_um3 = float(fields[1])
                else:
                    raise ValueError("expected two or three columns")
            except ValueError as exc:
                raise ValueError(f"{input_path}:{line_number}: {exc}") from exc
            records.append(VolumeRecord(track_id, range_um, volume_um3))
    return records


@dataclass(frozen=True)
class LinearFit:
    slope: float
    slope_error: float


def fit_through_origin(
    x: np.ndarray, y: np.ndarray, sigma: np.ndarray | None = None
) -> LinearFit:
    if len(x) == 0 or not np.any(x):
        raise ValueError("at least one non-zero range value is required")
    if sigma is None:
        weights = np.ones_like(x)
    else:
        positive = sigma > 0
        fallback = float(np.median(sigma[positive])) if np.any(positive) else 1.0
        weights = 1.0 / np.where(positive, sigma, fallback) ** 2
    denominator = float(np.sum(weights * x * x))
    slope = float(np.sum(weights * x * y) / denominator)
    residual = y - slope * x
    degrees = max(1, len(x) - 1)
    variance_scale = float(np.sum(weights * residual**2) / degrees)
    slope_error = math_sqrt_nonnegative(variance_scale / denominator)
    return LinearFit(slope, slope_error)


def math_sqrt_nonnegative(value: float) -> float:
    return float(np.sqrt(max(0.0, value)))


def _group_reference(
    records: list[VolumeRecord],
    bin_width_um: float,
    maximum_range_um: float,
    maximum_volume_um3: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    x = np.array([row.range_um for row in records])
    y = np.array([row.cumulative_volume_um3 for row in records])
    mask = (x <= maximum_range_um) & (y <= maximum_volume_um3)
    x = x[mask]
    y = y[mask]
    means_x: list[float] = []
    means_y: list[float] = []
    std_x: list[float] = []
    std_y: list[float] = []
    for low in np.arange(0.0, maximum_range_um, bin_width_um):
        selected = (x >= low) & (x < low + bin_width_um)
        if np.any(selected):
            means_x.append(float(np.mean(x[selected])))
            means_y.append(float(np.mean(y[selected])))
            std_x.append(float(np.std(x[selected])))
            std_y.append(float(np.std(y[selected])))
    return tuple(np.array(values) for values in (means_x, means_y, std_x, std_y))


def create_volume_range_plot(
    reference_path: str | Path,
    output_path: str | Path,
    candidate_path: str | Path | None = None,
    scores_path: str | Path | None = None,
    bin_width_um: float = 5.0,
    reference_maximum_range_um: float = 30.0,
    maximum_volume_um3: float = 5.0,
    x_limit_um: float = 50.0,
    y_limit_um3: float = 10.0,
) -> LinearFit:
    reference = read_volume_records(reference_path)
    means_x, means_y, std_x, std_y = _group_reference(
        reference,
        bin_width_um,
        reference_maximum_range_um,
        maximum_volume_um3,
    )
    if len(means_x) < 2:
        raise ValueError("reference data did not populate at least two range bins")
    fit = fit_through_origin(means_x, means_y, std_y)

    figure, axis = plt.subplots(figsize=(8, 6))
    axis.errorbar(
        means_x,
        means_y,
        xerr=std_x,
        yerr=std_y,
        fmt="o",
        color="black",
        ecolor="gray",
        capsize=3,
        label="reference (binned)",
    )
    x_fit = np.linspace(0.0, x_limit_um, 200)
    axis.plot(x_fit, fit.slope * x_fit, "--", color="blue", label=f"reference slope={fit.slope:.4f}")
    if fit.slope_error > 0:
        axis.fill_between(
            x_fit,
            (fit.slope - fit.slope_error) * x_fit,
            (fit.slope + fit.slope_error) * x_fit,
            color="blue",
            alpha=0.15,
            label="reference ±1σ",
        )

    score_rows: list[dict[str, object]] = []
    if candidate_path is not None:
        candidates = read_volume_records(candidate_path)
        grouped: dict[int, list[VolumeRecord]] = {}
        for row in candidates:
            if row.cumulative_volume_um3 <= maximum_volume_um3:
                grouped.setdefault(row.track_id, []).append(row)
        for track_id, rows in grouped.items():
            rows.sort(key=lambda row: row.range_um)
            x = np.array([row.range_um for row in rows])
            y = np.array([row.cumulative_volume_um3 for row in rows])
            axis.plot(x, y, "x-", alpha=0.8, label=f"candidate track {track_id}")
            candidate_fit = fit_through_origin(x, y)
            z_score = (
                (candidate_fit.slope - fit.slope) / fit.slope_error
                if fit.slope_error > 0
                else float("nan")
            )
            score_rows.append(
                {
                    "track_id": track_id,
                    "slope_um2": candidate_fit.slope,
                    "reference_slope_um2": fit.slope,
                    "slope_ratio": candidate_fit.slope / fit.slope,
                    "reference_z_score": z_score,
                    "consistent_with_reference_3sigma": abs(z_score) <= 3.0,
                }
            )

    axis.set(xlim=(0, x_limit_um), ylim=(0, y_limit_um3))
    axis.set_xlabel("Range [µm]")
    axis.set_ylabel("Cumulative volume [µm³]")
    axis.set_title("Track volume versus range")
    axis.grid(alpha=0.2)
    axis.legend()
    figure.tight_layout()
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)

    if scores_path is not None:
        score_output = Path(scores_path)
        score_output.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "track_id",
            "slope_um2",
            "reference_slope_um2",
            "slope_ratio",
            "reference_z_score",
            "consistent_with_reference_3sigma",
        ]
        with score_output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(score_rows)
    return fit
