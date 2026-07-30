#!/usr/bin/env python3
"""Combine per-image-stack thickness files."""

from __future__ import annotations

import argparse

from thickness_analysis.summary import summarize


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Combine thickness results. Inputs may be files, directories, or "
            "glob patterns; track IDs are made globally unique by default."
        )
    )
    parser.add_argument("inputs", nargs="+", help="input file/directory/glob")
    parser.add_argument("-o", "--output", required=True, help="combined output")
    parser.add_argument(
        "--keep-track-ids",
        action="store_true",
        help="do not renumber track IDs across input files",
    )
    args = parser.parse_args()
    file_count, row_count = summarize(
        args.inputs, args.output, renumber=not args.keep_track_ids
    )
    print(f"Combined {row_count} rows from {file_count} files into {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
