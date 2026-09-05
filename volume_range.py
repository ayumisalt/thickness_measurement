#!/usr/bin/env python3
"""Plot volume versus range and compare unknown tracks with a reference."""

from __future__ import annotations

import argparse

from thickness_analysis.quality_cli import (
    add_quality_cut_arguments,
    quality_cuts_from_args,
)
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
        "--input-type",
        choices=("volume", "thickness"),
        default="volume",
        help="read precomputed volume data or thickness data (default: volume)",
    )
    parser.add_argument(
        "--scores-output",
        help="optional CSV with per-track slope comparison scores",
    )
    parser.add_argument("--bin-width-um", type=float, default=5.0)
    parser.add_argument("--reference-max-range-um", type=float, default=30.0)
    parser.add_argument("--maximum-volume-um3", type=float, default=5.0)
    parser.add_argument("--x-limit-um", type=float, default=50.0)
    parser.add_argument("--y-limit-um3", type=float, default=10.0)
    parser.add_argument(
        "--minimum-reference-tracks-per-bin",
        type=int,
        default=1,
        help="omit reference bins with fewer unique tracks (default: 1)",
    )
    add_quality_cut_arguments(parser)
    args = parser.parse_args()
    cuts = quality_cuts_from_args(parser, args)
    if args.input_type != "thickness" and cuts.requested:
        parser.error("fit-quality cuts require --input-type thickness")
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
        input_type=args.input_type,
        quality_cuts=cuts,
        minimum_reference_tracks_per_bin=args.minimum_reference_tracks_per_bin,
    )
    print(
        f"Wrote {args.output}; reference slope = "
        f"{fit.slope:.6g} ± {fit.slope_error:.3g} µm²"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
