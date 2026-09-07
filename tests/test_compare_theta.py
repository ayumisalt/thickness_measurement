import csv
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from thickness_analysis.io import ThicknessRecord, write_thickness_records


class ThetaScanTest(unittest.TestCase):
    def test_scan_outputs_and_sparse_bins(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "coords.txt").write_text("1 0 0 0\n1 1 0 1\n2 0 0 0\n2 1 0 -1\n")
            rows = [ThicknessRecord(i, d, 0, 200, 0, fit_r2=.99,
                                    width_relative_error=.05, fit_p_value=.5, noise_sigma=1)
                    for i in [1, 2] for d in range(1, 10)]
            write_thickness_records(root / "reference.txt", rows,
                                    [f"tracks: {root / 'coords.txt'}", "input_shrink: 1"])
            write_thickness_records(root / "candidate.txt", [r for r in rows if r.track_id == 1])
            (root / "candidate_angles.txt").write_text("1 50\n")
            cmd = [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/compare-theta.py"),
                   str(root / "reference.txt"), "--candidate", str(root / "candidate.txt"),
                   "--candidate-angles", str(root / "candidate_angles.txt"),
                   "--output-dir", str(root / "out"), "--windows", "0", "5", "10", "15",
                   "--minimum-reference-tracks-per-bin", "2"]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            with (root / "out/comparison_summary.csv").open() as stream:
                summary = list(csv.DictReader(stream))
            self.assertEqual(len(summary), 10)
            sparse = [r for r in summary if r["condition"].startswith("theta0_")]
            self.assertTrue(all(r["status"] == "insufficient_reference_bins" for r in sparse))
            valid = [r for r in summary if r not in sparse]
            self.assertTrue(all(r["status"] == "ok" for r in valid))
            self.assertTrue(all(r["reference_valid_tracks"] == "2" for r in valid))
            self.assertEqual(len(list((root / "out").glob("*.png"))), 8)
            # Reruns must preserve all existing products.
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already exists", result.stderr)


if __name__ == "__main__":
    unittest.main()
