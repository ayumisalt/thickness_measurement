#!/usr/bin/env python3
"""Integrate track cross-sections into cumulative volume."""

from __future__ import annotations

import argparse

from thickness_analysis.quality_cli import (
    add_quality_cut_arguments,
    quality_cuts_from_args,
)
from thickness_analysis.volume import run_volume


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Treat each fitted width as a cylinder diameter and integrate "
            "cumulative volume along each track."
        )
    )
    parser.add_argument("input", help="combined thickness text")
    parser.add_argument("-o", "--output", required=True, help="volume output text")
    add_quality_cut_arguments(parser)
    args = parser.parse_args()
    cuts = quality_cuts_from_args(parser, args)
    input_rows, output_rows = run_volume(
        args.input, args.output, quality_cuts=cuts
    )
    print(
        f"Wrote {output_rows} volume points from "
        f"{input_rows} thickness measurements to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
