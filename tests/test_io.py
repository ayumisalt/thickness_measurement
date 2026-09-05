from pathlib import Path
import tempfile
import unittest

from thickness_analysis.io import (
    ThicknessRecord,
    load_tracks,
    read_thickness_records,
    write_thickness_records,
)


class TrackInputTest(unittest.TestCase):
    def test_five_column_input_preserves_polyline_and_applies_shrink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tracks.txt"
            path.write_text(
                "# Shrink: 2\n"
                "1 7 1.0 2.0 6.0\n"
                "1 7 2.0 3.0 8.0\n"
                "1 7 4.0 5.0 10.0\n",
                encoding="utf-8",
            )
            tracks, shrink = load_tracks(path)
        self.assertEqual(shrink, 2.0)
        self.assertEqual(tracks[0].track_id, 7)
        self.assertEqual(len(tracks[0].points), 3)
        self.assertEqual(tracks[0].endpoints[0].z_mm, 3.0)
        self.assertEqual(tracks[0].endpoints[1].z_mm, 5.0)
        self.assertEqual(tracks[0].points[1].z_mm, 4.0)

    def test_four_column_input_defaults_to_unshrunk_z(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tracks.txt"
            path.write_text("2 1.0 2.0 3.0\n2 4.0 5.0 6.0\n", encoding="utf-8")
            tracks, shrink = load_tracks(path)
        self.assertEqual(shrink, 1.0)
        self.assertEqual(tracks[0].endpoints[1].z_mm, 6.0)

    def test_thickness_quality_columns_round_trip(self) -> None:
        row = ThicknessRecord(
            1,
            2.0,
            300.0,
            700.0,
            200.0,
            contrast=80.0,
            fit_r2=0.98,
            fit_nrmse=0.03,
            reduced_chi2=1.2,
            fit_p_value=0.25,
            width_error_nm=50.0,
            width_relative_error=0.071,
            noise_sigma=4.5,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "thickness.txt"
            write_thickness_records(path, [row])
            result = read_thickness_records(path)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].noise_sigma, 4.5)
        self.assertAlmostEqual(result[0].fit_p_value, 0.25)


if __name__ == "__main__":
    unittest.main()
