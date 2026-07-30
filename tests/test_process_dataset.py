import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


class ProcessDatasetTest(unittest.TestCase):
    def test_dry_run_skips_area_without_track_input(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        script = repository / "scripts" / "process-dataset.py"

        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            data_parent = temporary_path / "data"
            measured = data_parent / "AREA00_alpha_0000"
            skipped = data_parent / "AREA00_alpha_0001"
            measured.mkdir(parents=True)
            skipped.mkdir()
            (measured / "image.json").write_text("{}\n", encoding="utf-8")
            (measured / "image.jsonTrackForUguisFitting.txt").write_text(
                "# intentionally minimal for dry-run\n", encoding="utf-8"
            )
            (skipped / "image.json").write_text("{}\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(data_parent),
                    "--dry-run",
                    "--thickness-dir",
                    str(temporary_path / "per-area"),
                    "--results-dir",
                    str(temporary_path / "results"),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("Skipping 1 area(s) without track input", completed.stdout)
            self.assertIn("AREA00_alpha_0001", completed.stdout)
            self.assertIn(
                "Selected 1 of 2 matching area(s) for processing", completed.stdout
            )
            self.assertIn("AREA00_alpha_0000/image.json", completed.stdout)
            self.assertNotIn("AREA00_alpha_0001/image.json ", completed.stdout)
            self.assertFalse((temporary_path / "results").exists())


if __name__ == "__main__":
    unittest.main()
