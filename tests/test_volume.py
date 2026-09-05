import math
import unittest

from thickness_analysis.io import ThicknessRecord
from thickness_analysis.thickness import (
    _Polyline,
    _fit_profile,
    edge_resolution_nm,
    inflection_width_nm,
    tanh_gaussian,
)
from thickness_analysis.io import Track, TrackPoint
from thickness_analysis.volume import (
    QualityCuts,
    calculate_volumes,
    calculate_volumes_with_quality,
    passes_quality,
)

import numpy as np


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

    def test_quality_rejection_interpolates_interior_width(self) -> None:
        rows = [
            ThicknessRecord(1, 1.0, 0, 200.0, 0, fit_r2=0.99),
            ThicknessRecord(1, 2.0, 0, 2000.0, 0, fit_r2=0.10),
            ThicknessRecord(1, 3.0, 0, 400.0, 0, fit_r2=0.99),
        ]
        result = calculate_volumes_with_quality(
            rows, QualityCuts(minimum_fit_r2=0.9)
        )
        expected = math.pi * (0.1**2 + 0.15**2 + 0.2**2)
        self.assertEqual([row.range_um for row in result], [1.0, 2.0, 3.0])
        self.assertAlmostEqual(result[-1].cumulative_volume_um3, expected)

    def test_polyline_uses_local_segment_direction_and_3d_arc_length(self) -> None:
        track = Track(
            4,
            (
                TrackPoint(0.0, 0.0, 0.0),
                TrackPoint(0.003, 0.0, 0.004),
                TrackPoint(0.003, 0.004, 0.004),
            ),
        )
        polyline = _Polyline.from_track(track)
        first_point, first_direction = polyline.sample(2.5)
        second_point, second_direction = polyline.sample(7.0)
        self.assertAlmostEqual(polyline.length_um, 9.0)
        np.testing.assert_allclose(first_point, [0.0015, 0.0, 0.002])
        np.testing.assert_allclose(first_direction, [1.0, 0.0])
        np.testing.assert_allclose(second_point, [0.003, 0.002, 0.004])
        np.testing.assert_allclose(second_direction, [0.0, 1.0])

    def test_profile_noise_and_p_value_are_data_driven(self) -> None:
        rng = np.random.default_rng(12345)
        x = np.linspace(-2000.0, 2000.0, 121)
        brightness = tanh_gaussian(x, 1.2, 20.0, 220.0, 90.0)
        brightness += rng.normal(0.0, 5.0, size=len(x))
        fit = _fit_profile(x, brightness)
        self.assertIsNotNone(fit)
        assert fit is not None
        self.assertGreater(fit.noise_sigma, 1.0)
        self.assertLess(fit.noise_sigma, 12.0)
        self.assertGreaterEqual(fit.fit_p_value, 0.0)
        self.assertLessEqual(fit.fit_p_value, 1.0)
        self.assertNotEqual(fit.fit_p_value, 1.0)

    def test_p_value_is_available_as_a_quality_cut(self) -> None:
        accepted = ThicknessRecord(
            1, 1.0, 0.0, 200.0, 0.0, fit_p_value=0.05
        )
        rejected = ThicknessRecord(
            1, 2.0, 0.0, 200.0, 0.0, fit_p_value=0.001
        )
        cuts = QualityCuts(minimum_fit_p_value=0.01)
        self.assertTrue(passes_quality(accepted, cuts))
        self.assertFalse(passes_quality(rejected, cuts))


if __name__ == "__main__":
    unittest.main()
