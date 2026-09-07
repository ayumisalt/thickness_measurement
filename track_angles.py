#!/usr/bin/env python3
"""Export acquisition-coordinate track angles following thickness provenance."""

import argparse
import json
from pathlib import Path

from thickness_analysis.angles import build_angle_table


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="thickness file, including combined results")
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--path-map", action="append", default=[], metavar="OLD=NEW",
                        help="relocate an absolute provenance path prefix; repeatable")
    args = parser.parse_args()
    maps = []
    for item in args.path_map:
        if "=" not in item:
            parser.error("--path-map requires OLD=NEW")
        old, new = (Path(s).expanduser() for s in item.split("=", 1))
        if not old.is_absolute() or not new.is_absolute():
            parser.error("--path-map prefixes must be absolute")
        maps.append((old, new))
    rows = build_angle_table(args.input, maps)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as stream:
        stream.write("# endpoint polar theta in acquisition coordinates (z / measurement Shrink)\n")
        stream.write("# columns: track_id theta_deg folded_theta_deg local_folded_min_deg local_folded_max_deg\n")
        for track_id, theta, folded, low, high, source, local_id, shrink in rows:
            stream.write("# provenance: " + json.dumps(dict(track_id=track_id, coordinate_path=source,
                         local_track_id=local_id, shrink=shrink), ensure_ascii=False) + "\n")
            stream.write(f"{track_id} {theta:.12f} {folded:.12f} {low:.12f} {high:.12f}\n")
    print(f"Wrote {len(rows)} track angles to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
