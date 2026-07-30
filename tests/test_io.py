from pathlib import Path
import tempfile
import unittest

from thickness_analysis.io import load_tracks


class TrackInputTest(unittest.TestCase):
    def test_five_column_input_uses_header_shrink_and_outer_endpoints(self) -> None:
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
        self.assertEqual(tracks[0].endpoints[0].z_mm, 3.0)
        self.assertEqual(tracks[0].endpoints[1].z_mm, 5.0)

    def test_four_column_input_defaults_to_unshrunk_z(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tracks.txt"
            path.write_text("2 1.0 2.0 3.0\n2 4.0 5.0 6.0\n", encoding="utf-8")
            tracks, shrink = load_tracks(path)
        self.assertEqual(shrink, 1.0)
        self.assertEqual(tracks[0].endpoints[1].z_mm, 6.0)


if __name__ == "__main__":
    unittest.main()
