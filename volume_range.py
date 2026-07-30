#!/usr/bin/env python3
"""Plot volume versus range and compare unknown tracks with a reference."""

from __future__ import annotations

import argparse

from thickness_analysis.visualize import create_volume_range_plot


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a volume-range calibration/comparison plot."
    )
    parser.add_argument("reference", help="reference cumulative-volume text")
    parser.add_argument(
        "candidate", nargs="?", help="optional unknown/candidate volume text"
    )
    parser.add_argument("-o", "--output", required=True, help="output PNG/PDF")
    parser.add_argument(
        "--scores-output",
        help="optional CSV with per-track slope comparison scores",
    )
    parser.add_argument("--bin-width-um", type=float, default=5.0)
    parser.add_argument("--reference-max-range-um", type=float, default=30.0)
    parser.add_argument("--maximum-volume-um3", type=float, default=5.0)
    parser.add_argument("--x-limit-um", type=float, default=50.0)
    parser.add_argument("--y-limit-um3", type=float, default=10.0)
    args = parser.parse_args()
    fit = create_volume_range_plot(
        reference_path=args.reference,
        candidate_path=args.candidate,
        output_path=args.output,
        scores_path=args.scores_output,
        bin_width_um=args.bin_width_um,
        reference_maximum_range_um=args.reference_max_range_um,
        maximum_volume_um3=args.maximum_volume_um3,
        x_limit_um=args.x_limit_um,
        y_limit_um3=args.y_limit_um3,
    )
    print(
        f"Wrote {args.output}; reference slope = "
        f"{fit.slope:.6g} ± {fit.slope_error:.3g} µm²"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
