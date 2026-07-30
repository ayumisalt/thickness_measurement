import math
import unittest

from thickness_analysis.io import ThicknessRecord
from thickness_analysis.thickness import edge_resolution_nm, inflection_width_nm
from thickness_analysis.volume import calculate_volumes


class VolumeTest(unittest.TestCase):
    def test_cylinder_volume_and_rejected_width_gap(self) -> None:
        rows = [
            ThicknessRecord(1, 1.0, 0, 1000.0, 0),  # rejected
            ThicknessRecord(1, 2.0, 0, 200.0, 0),
            ThicknessRecord(1, 3.0, 0, 200.0, 0),
        ]
        result = calculate_volumes(rows, maximum_width_nm=800)
        expected_slice = math.pi * 0.1**2
        self.assertEqual([row.range_um for row in result], [2.0, 3.0])
        self.assertAlmostEqual(result[0].cumulative_volume_um3, expected_slice)
        self.assertAlmostEqual(result[1].cumulative_volume_um3, 2 * expected_slice)

    def test_fitted_width_metrics_are_positive(self) -> None:
        self.assertGreater(edge_resolution_nm(1.0, 200.0), 0)
        self.assertGreater(inflection_width_nm(1.0, 200.0), 0)


if __name__ == "__main__":
    unittest.main()
