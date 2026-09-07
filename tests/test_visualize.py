import csv
from pathlib import Path
import tempfile
import unittest

from thickness_analysis.io import ThicknessRecord, write_thickness_records
from thickness_analysis.visualize import create_volume_range_plot
from thickness_analysis.volume import QualityCuts


class VisualizeTest(unittest.TestCase):
    def test_angle_matching_excludes_thick_reference_and_reflects_z(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = [ThicknessRecord(i, d, 0, w, 0, theta_deg={1:75,2:105,3:20}[i])
                         for i, w in [(1, 200), (2, 200), (3, 2000)]
                         for d in [1, 2, 3, 4]]
            candidate = [ThicknessRecord(9, d, 0, 200, 0, theta_deg=75) for d in [1, 2, 3, 4]]
            write_thickness_records(root / "ref.txt", reference)
            write_thickness_records(root / "cand.txt", candidate)
            (root / "ref_angles.txt").write_text("1 75\n2 105\n3 20\n")
            (root / "cand_angles.txt").write_text("9 75\n")
            fit = create_volume_range_plot(
                root / "ref.txt", root / "plot.png", root / "cand.txt", root / "scores.csv",
                input_type="thickness", bin_width_um=2, reference_maximum_range_um=5,
                minimum_reference_tracks_per_bin=2,
                reference_angles_path=root / "ref_angles.txt",
                candidate_angles_path=root / "cand_angles.txt", theta_window_deg=0)
            import math
            self.assertAlmostEqual(fit.slope, math.pi * .1**2)
            direct = create_volume_range_plot(
                root / "ref.txt", root / "direct.png", root / "cand.txt",
                input_type="thickness", bin_width_um=2, reference_maximum_range_um=5,
                minimum_reference_tracks_per_bin=2, theta_window_deg=0)
            self.assertEqual(direct, fit)

    def test_thickness_quality_cuts_feed_plot_and_scores(self) -> None:
        reference: list[ThicknessRecord] = []
        for track_id, width in ((1, 200.0), (2, 220.0)):
            for distance in (1.0, 2.0, 3.0, 4.0):
                reference.append(
                    ThicknessRecord(
                        track_id,
                        distance,
                        0.0,
                        width,
                        0.0,
                        fit_r2=0.99,
                        width_relative_error=0.05,
                    )
                )
        candidate = [
            ThicknessRecord(9, 1.0, 0.0, 210.0, 0.0, fit_r2=0.99),
            ThicknessRecord(9, 2.0, 0.0, 2000.0, 0.0, fit_r2=0.1),
            ThicknessRecord(9, 3.0, 0.0, 210.0, 0.0, fit_r2=0.99),
            ThicknessRecord(9, 4.0, 0.0, 210.0, 0.0, fit_r2=0.99),
        ]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference_path = root / "reference.txt"
            candidate_path = root / "candidate.txt"
            output_path = root / "plot.png"
            scores_path = root / "scores.csv"
            write_thickness_records(reference_path, reference)
            write_thickness_records(candidate_path, candidate)
            create_volume_range_plot(
                reference_path,
                output_path,
                candidate_path,
                scores_path,
                bin_width_um=2.0,
                reference_maximum_range_um=5.0,
                input_type="thickness",
                quality_cuts=QualityCuts(minimum_fit_r2=0.9),
                minimum_reference_tracks_per_bin=2,
            )
            with scores_path.open(encoding="utf-8") as stream:
                scores = list(csv.DictReader(stream))

            self.assertTrue(output_path.is_file())
            self.assertEqual(len(scores), 1)
            self.assertEqual(scores[0]["track_id"], "9")
            self.assertEqual(scores[0]["n_volume_points"], "4")
            self.assertIn("combined_uncertainty_z_score", scores[0])


if __name__ == "__main__":
    unittest.main()
