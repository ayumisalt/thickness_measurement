#!/usr/bin/env python3
"""Measure transverse widths along tracks in a microscope z-stack."""

from __future__ import annotations

import argparse
from pathlib import Path

from thickness_analysis.io import load_image_stack, load_tracks, write_thickness_records
from thickness_analysis.thickness import ThicknessConfig, measure_tracks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Measure track thickness. For a multi-point track, the first and last "
            "points are used as the endpoints."
        )
    )
    parser.add_argument("image_json", help="microscope image-stack metadata JSON")
    parser.add_argument("tracks", help="four- or five-column initial track text")
    parser.add_argument(
        "-o",
        "--output",
        help="output text (default: track_thickness.txt next to the track input)",
    )
    parser.add_argument(
        "--track-id",
        action="append",
        type=int,
        help="measure only this track ID; may be specified more than once",
    )
    parser.add_argument(
        "--shrink",
        type=float,
        help="override the '# Shrink:' value in the track file",
    )
    parser.add_argument("--spacing-um", type=float, default=1.0)
    parser.add_argument("--endpoint-margin-um", type=float, default=2.0)
    parser.add_argument("--profile-half-width-um", type=float, default=2.0)
    parser.add_argument("--focus-search-frames", type=int, default=25)
    parser.add_argument("--minimum-contrast", type=float, default=50.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    stack = load_image_stack(args.image_json)
    tracks, shrink = load_tracks(args.tracks, args.shrink)
    if args.track_id:
        selected = set(args.track_id)
        tracks = [track for track in tracks if track.track_id in selected]
        missing = selected - {track.track_id for track in tracks}
        if missing:
            raise SystemExit(f"track IDs not found: {sorted(missing)}")
    config = ThicknessConfig(
        spacing_um=args.spacing_um,
        endpoint_margin_um=args.endpoint_margin_um,
        transverse_half_width_um=args.profile_half_width_um,
        focus_search_frames=args.focus_search_frames,
        minimum_contrast=args.minimum_contrast,
    )
    records = measure_tracks(stack, tracks, config)
    output = (
        Path(args.output)
        if args.output
        else Path(args.tracks).expanduser().resolve().parent / "track_thickness.txt"
    )
    write_thickness_records(
        output,
        records,
        comments=[
            f"image_json: {stack.json_path}",
            f"tracks: {Path(args.tracks).expanduser().resolve()}",
            f"input_shrink: {shrink:g}",
            "multi-point policy: first and last point are endpoints",
        ],
    )
    measured = len({row.track_id for row in records})
    print(
        f"Wrote {len(records)} measurements from {measured}/{len(tracks)} "
        f"tracks to {output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
