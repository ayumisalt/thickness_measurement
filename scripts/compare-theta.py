#!/usr/bin/env python3
"""Recombine alpha results and compare angle windows with two quality cuts."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from thickness_analysis.angles import build_angle_table, read_angles, select_reference_ids
from thickness_analysis.io import read_thickness_records
from thickness_analysis.summary import summarize
from thickness_analysis.visualize import _group_reference, create_volume_range_plot
from thickness_analysis.volume import QualityCuts, calculate_volumes_with_quality, passes_quality


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("references", nargs="+")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--candidate-angles", help="precomputed table, if candidate coordinates are elsewhere")
    parser.add_argument("--output-dir", required=True, help="must not already exist")
    parser.add_argument("--path-map", action="append", default=[], metavar="OLD=NEW")
    parser.add_argument("--windows", type=float, nargs="+", default=[5, 10, 15])
    parser.add_argument("--minimum-reference-tracks-per-bin", type=int, default=10)
    parser.add_argument("--maximum-volume-um3", type=float, default=5.0)
    args = parser.parse_args()
    import math
    if any(not math.isfinite(w) or not 0 <= w <= 90 for w in args.windows):
        parser.error("windows must be finite and between 0 and 90")
    if len(set(args.windows)) != len(args.windows):
        parser.error("duplicate windows")
    if args.minimum_reference_tracks_per_bin < 1:
        parser.error("minimum reference tracks per bin must be positive")
    if not math.isfinite(args.maximum_volume_um3) or args.maximum_volume_um3 <= 0:
        parser.error("maximum volume must be finite and positive")
    maps = []
    for item in args.path_map:
        if "=" not in item:
            parser.error("--path-map requires OLD=NEW")
        pair = tuple(Path(s).expanduser() for s in item.split("=", 1))
        if not all(p.is_absolute() for p in pair):
            parser.error("--path-map prefixes must be absolute")
        maps.append(pair)
    out = Path(args.output_dir).resolve()
    if out.exists():
        parser.error("output directory already exists; use a new name to preserve results")
    out.mkdir(parents=True)
    combined = out / "reference_thickness.txt"
    summarize(args.references, combined)

    def make_angles(source, destination):
        rows = build_angle_table(source, maps)
        destination.write_text("# track_id theta_deg folded_theta_deg local_min_deg local_max_deg\n" +
                               "".join(" ".join(map(str, r[:5])) + "\n" for r in rows))
        (destination.with_suffix(".provenance.json")).write_text(json.dumps(rows, indent=2))
        return read_angles(destination)

    ref_angles_path = out / "reference_angles.txt"
    ref_angles = make_angles(combined, ref_angles_path)
    cand_angles_path = out / "candidate_angles.txt"
    if args.candidate_angles:
        cand_angles_path.write_text(Path(args.candidate_angles).read_text())
        cand_angles = read_angles(cand_angles_path)
    else:
        cand_angles = make_angles(args.candidate, cand_angles_path)
    reference = read_thickness_records(combined)
    candidate = read_thickness_records(args.candidate)
    ref_ids, cand_ids = {r.track_id for r in reference}, {r.track_id for r in candidate}
    # Validate coverage and single-candidate assumption even for the no-angle baseline.
    _, center = select_reference_ids(ref_ids, ref_angles, cand_ids, cand_angles, 90)
    manifest = dict(arguments=vars(args), python=sys.version, candidate_folded_theta_deg=center,
                    bin_width_um=5, reference_max_range_um=30,
                    input_sha256={str(Path(p).resolve()): hashlib.sha256(Path(p).read_bytes()).hexdigest()
                                  for p in [*args.references, args.candidate]})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    summary, bins, selected_tracks = [], [], []
    for window in [None, *args.windows]:
        ids = ref_ids if window is None else select_reference_ids(
            ref_ids, ref_angles, cand_ids, cand_angles, window)[0]
        angle_name = "all_angles" if window is None else f"theta{window:g}"
        subset = [r for r in reference if r.track_id in ids]
        for track_id in sorted(ids):
            selected_tracks.append(dict(window=angle_name, track_id=track_id, theta_deg=ref_angles[track_id]))
        for quality in ["base", "p001"]:
            cuts = QualityCuts(minimum_fit_r2=.9, maximum_width_relative_error=.2,
                               minimum_fit_p_value=.01 if quality == "p001" else None)
            ref_volume = calculate_volumes_with_quality(subset, cuts)
            cand_volume = calculate_volumes_with_quality(candidate, cuts)
            accepted = Counter(r.track_id for r in subset if passes_quality(r, cuts))
            candidate_accepted = sum(passes_quality(r, cuts) for r in candidate)
            label = f"{angle_name}_{quality}"
            grouped = _group_reference(ref_volume, 5, 30, args.maximum_volume_um3,
                                       args.minimum_reference_tracks_per_bin)
            for low in range(0, 30, 5):
                points = [r for r in ref_volume if low <= r.range_um < low + 5
                          and r.cumulative_volume_um3 <= args.maximum_volume_um3]
                n = len({r.track_id for r in points})
                bins.append(dict(condition=label, low_um=low, high_um=low+5,
                                 n_tracks=n, n_volume_points=len(points),
                                 retained=n >= args.minimum_reference_tracks_per_bin))
            row = dict(condition=label, theta_window_deg=window, candidate_folded_theta_deg=center,
                       reference_angle_tracks=len(ids), reference_angle_points=len(subset),
                       reference_accepted_points=sum(accepted.values()),
                       reference_accepted_points_on_valid_tracks=sum(n for n in accepted.values() if n >= 2),
                       reference_valid_tracks=sum(n >= 2 for n in accepted.values()),
                       reference_bins=len(grouped[0]), candidate_accepted_points=candidate_accepted,
                       candidate_valid_tracks=len({r.track_id for r in cand_volume}),
                       status="ok", track_id="", n_volume_points="", slope_um2="", slope_error_um2="",
                       reference_slope_um2="", reference_slope_error_um2="", slope_ratio="",
                       reference_z_score="", combined_uncertainty_z_score="",
                       consistent_with_reference_3sigma="")
            if len(grouped[0]) < 2:
                row["status"] = "insufficient_reference_bins"
            elif not any(r.cumulative_volume_um3 <= args.maximum_volume_um3 for r in cand_volume):
                row["status"] = "no_candidate_fit_points"
            else:
                scores = out / f"scores_{label}.csv"
                create_volume_range_plot(combined, out / f"volume_range_{label}.png",
                                         args.candidate, scores, input_type="thickness", quality_cuts=cuts,
                                         minimum_reference_tracks_per_bin=args.minimum_reference_tracks_per_bin,
                                         maximum_volume_um3=args.maximum_volume_um3,
                                         reference_angles_path=ref_angles_path if window is not None else None,
                                         candidate_angles_path=cand_angles_path if window is not None else None,
                                         theta_window_deg=window)
                with scores.open() as stream:
                    row.update(next(csv.DictReader(stream)))
            summary.append(row)
            print(label, row["status"], "tracks=", row["reference_valid_tracks"],
                  "bins=", row["reference_bins"], "reference slope=", row["reference_slope_um2"])
    write_csv(out / "comparison_summary.csv", summary)
    write_csv(out / "reference_bins.csv", bins)
    write_csv(out / "selected_reference_tracks.csv", selected_tracks)
    print(f"Wrote comparison to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
