from pathlib import Path
import tempfile
import unittest

from thickness_analysis.io import read_thickness_records
from thickness_analysis.summary import summarize


class SummaryTest(unittest.TestCase):
    def test_track_ids_are_unique_across_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            header = "# columns: track_id distance_um resolution_nm width_nm sigma_nm\n"
            (root / "a.txt").write_text(
                header + "0 1 10 100 20\n0 2 11 110 21\n", encoding="utf-8"
            )
            (root / "b.txt").write_text(
                header + "0 1 12 120 22\n2 1 13 130 23\n", encoding="utf-8"
            )
            output = root / "combined.txt"
            files, rows = summarize(
                [str(root / "a.txt"), str(root / "b.txt")], output
            )
            result = read_thickness_records(output)
        self.assertEqual((files, rows), (2, 4))
        self.assertEqual([row.track_id for row in result], [1, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()
