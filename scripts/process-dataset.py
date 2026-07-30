#!/usr/bin/env python3
"""Run the complete thickness-to-volume pipeline over multiple areas."""

from __future__ import annotations

import argparse
from pathlib import Path
import shlex
import subprocess
import sys


def run(command: list[str], dry_run: bool) -> None:
    print("+", shlex.join(command), flush=True)
    if not dry_run:
        subprocess.run(command, check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Process every matching area: measure thickness, combine tracks, "
            "calculate cumulative volume, and create a volume-range plot."
        )
    )
    parser.add_argument("data_parent", help="directory containing area directories")
    parser.add_argument(
        "--pattern", default="AREA00_alpha_*", help="area directory glob pattern"
    )
    parser.add_argument(
        "--backend",
        choices=("python", "root"),
        default="python",
        help="implementation used for every pipeline stage",
    )
    parser.add_argument(
        "--track-file",
        default="image.jsonTrackForUguisFitting.txt",
        help="track input filename inside each area",
    )
    parser.add_argument(
        "--area-output-name",
        default="track_thickness.txt",
        help="per-area thickness output filename",
    )
    parser.add_argument(
        "--results-dir",
        default="results/dataset",
        help="directory for combined results and plots",
    )
    parser.add_argument(
        "--build-dir",
        default="build",
        help="CMake build directory for the ROOT backend",
    )
    parser.add_argument(
        "--maximum-width-nm",
        type=float,
        default=800.0,
        help="maximum accepted fitted width during volume integration",
    )
    parser.add_argument(
        "--skip-thickness",
        action="store_true",
        help="reuse existing per-area thickness output files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print commands without executing them",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repository = Path(__file__).resolve().parents[1]
    data_parent = Path(args.data_parent).expanduser().resolve()
    results_dir = Path(args.results_dir).expanduser()
    if not results_dir.is_absolute():
        results_dir = (Path.cwd() / results_dir).resolve()
    build_dir = Path(args.build_dir).expanduser()
    if not build_dir.is_absolute():
        build_dir = (repository / build_dir).resolve()

    if not data_parent.is_dir():
        raise SystemExit(f"data parent is not a directory: {data_parent}")
    areas = sorted(path for path in data_parent.glob(args.pattern) if path.is_dir())
    if not areas:
        raise SystemExit(
            f"no area directories matched {args.pattern!r} under {data_parent}"
        )
    if not args.dry_run:
        results_dir.mkdir(parents=True, exist_ok=True)

    if args.backend == "python":
        thickness_program = [sys.executable, str(repository / "track_thickness.py")]
        summarize_program = [sys.executable, str(repository / "summarize_result.py")]
        volume_program = [sys.executable, str(repository / "track_volume.py")]
        plot_program = [sys.executable, str(repository / "volume_range.py")]
    else:
        programs = {
            name: build_dir / name
            for name in (
                "track_thickness_root",
                "summarize_result_root",
                "track_volume_root",
                "volume_range_root",
            )
        }
        if not args.dry_run:
            missing = [str(path) for path in programs.values() if not path.is_file()]
            if missing:
                raise SystemExit("missing ROOT executables: " + ", ".join(missing))
        thickness_program = [str(programs["track_thickness_root"])]
        summarize_program = [str(programs["summarize_result_root"])]
        volume_program = [str(programs["track_volume_root"])]
        plot_program = [str(programs["volume_range_root"])]

    area_inputs: list[tuple[Path, Path, Path, Path]] = []
    for area in areas:
        image_json = area / "image.json"
        track_file = area / args.track_file
        output = area / args.area_output_name
        if not args.dry_run:
            if args.skip_thickness:
                if not output.is_file():
                    raise SystemExit(f"missing reused thickness output: {output}")
            else:
                if not image_json.is_file():
                    raise SystemExit(f"missing image metadata: {image_json}")
                if not track_file.is_file():
                    raise SystemExit(f"missing track input: {track_file}")
        area_inputs.append((area, image_json, track_file, output))

    thickness_outputs: list[Path] = []
    for index, (area, image_json, track_file, output) in enumerate(
        area_inputs, start=1
    ):
        print(f"\n[{index}/{len(areas)}] {area.name}", flush=True)
        if not args.skip_thickness:
            run(
                thickness_program
                + [str(image_json), str(track_file), "-o", str(output)],
                args.dry_run,
            )
        thickness_outputs.append(output)

    combined = results_dir / f"all_track_thickness_{args.backend}.txt"
    volume = results_dir / f"volume_{args.backend}.txt"
    plot = results_dir / f"volume_range_{args.backend}.png"

    run(
        summarize_program
        + [str(path) for path in thickness_outputs]
        + ["-o", str(combined)],
        args.dry_run,
    )
    run(
        volume_program
        + [
            str(combined),
            "-o",
            str(volume),
            "--maximum-width-nm",
            str(args.maximum_width_nm),
        ],
        args.dry_run,
    )
    run(plot_program + [str(volume), "-o", str(plot)], args.dry_run)

    print("\nPipeline outputs:")
    print(f"  combined thickness: {combined}")
    print(f"  cumulative volume:  {volume}")
    print(f"  volume-range plot:  {plot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
