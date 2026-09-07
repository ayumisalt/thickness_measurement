from pathlib import Path
import tempfile
import unittest

from thickness_analysis.angles import (build_angle_table, folded_theta, read_angles,
                                       select_reference_ids, track_angles)
from thickness_analysis.io import Track, TrackPoint, ThicknessRecord, write_thickness_records


class AngleTest(unittest.TestCase):
    def test_embedded_angles_survive_combination_without_sources(self):
        from thickness_analysis.summary import summarize
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, theta in [('a', 75), ('b', 105)]:
                write_thickness_records(root / f'{name}.txt',
                    [ThicknessRecord(1, d, 0, 200, 0, theta_deg=theta, local_theta_deg=theta+1) for d in [1, 2]])
            summarize([str(root/'a.txt'), str(root/'b.txt')], root/'combined.txt')
            (root/'a.txt').unlink()
            (root/'b.txt').unlink()
            rows = build_angle_table(root/'combined.txt', [])
            self.assertEqual([r[1] for r in rows], [75, 105])

    def test_reflection_boundaries_and_missing_angles(self):
        self.assertEqual(folded_theta(75), folded_theta(105))
        angles = {1: 70, 2: 110, 3: 80, 4: 100, 5: 69.99, 6: 90}
        selected, center = select_reference_ids(set(angles), angles, {3}, {3: 105}, 5)
        self.assertEqual(selected, {1, 2, 3, 4})
        self.assertEqual(center, 75)
        for window in [-1, 91, float("nan")]:
            with self.assertRaises(ValueError):
                select_reference_ids(set(angles), angles, {3}, {3: 105}, window)
        with self.assertRaises(ValueError):
            select_reference_ids({99}, angles, {3}, {3: 105}, 5)
        with self.assertRaises(ValueError):
            select_reference_ids(set(angles), angles, {3, 4}, {3: 105}, 5)

    def test_geometry_and_nested_relocated_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "coords.txt").write_text("# Shrink: 9\n1 7 0 0 0\n1 7 1 0 -2\n")
            (root / "leaf.txt").write_text(
                "# tracks: /server/coords.txt\n# input_shrink: 2\n7 1 1 1 1\n")
            (root / "daily.txt").write_text(
                "# source_map: 4 <- /server/leaf.txt track 7\n4 1 1 1 1\n")
            (root / "combined.txt").write_text(
                "# source_map: 99 <- /server/daily.txt track 4\n99 1 1 1 1\n")
            rows = build_angle_table(root / "combined.txt", [(Path("/server"), root)])
            self.assertEqual(rows[0][0], 99)
            self.assertAlmostEqual(rows[0][1], 135)
            self.assertAlmostEqual(rows[0][2], 45)
            self.assertEqual(rows[0][-2:], (7, 2))
            (root / "angles.txt").write_text("1 75\n1 105\n")
            with self.assertRaises(ValueError):
                read_angles(root / "angles.txt")
            (root / "leaf.txt").write_text(
                "# source_map: 7 <- /server/combined.txt track 99\n7 1 1 1 1\n")
            with self.assertRaisesRegex(ValueError, "cycle"):
                build_angle_table(root / "combined.txt", [(Path("/server"), root)])

    def test_polyline_diagnostic_and_reversal(self):
        points = (TrackPoint(0, 0, 0), TrackPoint(1, 0, 0), TrackPoint(1, 0, 1))
        forward = track_angles(Track(1, points))
        backward = track_angles(Track(1, tuple(reversed(points))))
        self.assertAlmostEqual(folded_theta(forward[0]), folded_theta(backward[0]))
        self.assertEqual(forward[1:], (0, 90))
        with self.assertRaises(ValueError):
            track_angles(Track(1, (points[0], points[0])))


if __name__ == "__main__":
    unittest.main()
