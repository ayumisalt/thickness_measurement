#!/usr/bin/env python3
"""Integrate track cross-sections into cumulative volume."""

from __future__ import annotations

import argparse

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
    parser.add_argument(
        "--maximum-width-nm",
        type=float,
        default=800.0,
        help="reject wider fits (default: 800)",
    )
    args = parser.parse_args()
    input_rows, output_rows = run_volume(
        args.input, args.output, args.maximum_width_nm
    )
    print(
        f"Wrote {output_rows} accepted volume points from "
        f"{input_rows} thickness measurements to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
