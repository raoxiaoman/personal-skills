import bisect
import math
import unittest


# 仅定义隔离样例的线性、首尾保持契约，不是交付给项目的求值器。
def sample_value(points, frame, loop_length=None):
    frames = [p[0] for p in points]
    if not points or any(b <= a for a, b in zip(frames, frames[1:])):
        raise ValueError('points must be non-empty and strictly increasing')
    if not math.isfinite(frame):
        raise ValueError('frame must be finite')
    if loop_length is not None:
        if not math.isfinite(loop_length) or loop_length <= 0:
            raise ValueError('loop length must be positive')
        frame %= loop_length
    if frame <= frames[0]:
        return points[0][1]
    if frame >= frames[-1]:
        return points[-1][1]
    i = bisect.bisect_right(frames, frame)
    a, va = points[i - 1]
    b, vb = points[i]
    return va + (vb - va) * ((frame - a) / (b - a))


class KeyframeExampleTest(unittest.TestCase):
    points = [(0, 0), (18, 2.6), (25, 0)]

    def test_subframe_and_shared_endpoint(self):
        self.assertAlmostEqual(0.65, sample_value(self.points, 4.5))
        self.assertEqual(2.6, sample_value(self.points, 18))
        self.assertAlmostEqual(1.3, sample_value(self.points, 21.5))

    def test_explicit_hold_policy(self):
        self.assertEqual(0, sample_value(self.points, -1))
        self.assertEqual(0, sample_value(self.points, 25))
        self.assertEqual(0, sample_value(self.points, 200))

    def test_seek_reverse_and_repeated_frame(self):
        values = [sample_value(self.points, frame) for frame in (25, 4.5, 18, 4.5, 0)]
        for actual, expected in zip(values, (0, 0.65, 2.6, 0.65, 0)):
            self.assertAlmostEqual(expected, actual)

    def test_loop_period_is_not_inferred_from_last_point(self):
        points = [(0, 0), (10, 1)]
        self.assertEqual(1, sample_value(points, 15, 20))
        self.assertEqual(0, sample_value(points, 20, 20))
        self.assertEqual(1, sample_value(points, -5, 20))
        self.assertEqual(1, sample_value(points, 20))

    def test_reject_ambiguous_duplicate_and_invalid_cycle(self):
        with self.assertRaises(ValueError):
            sample_value([(0, 0), (0, 1)], 0)
        with self.assertRaises(ValueError):
            sample_value(self.points, 0, 0)

    def test_design_frame_conversion_is_not_hardcoded(self):
        self.assertEqual(12, 0.5 * 24)
        self.assertEqual(30, 0.5 * 60)
        self.assertNotEqual(12, 0.5 * 30)

    def test_known_bad_transformations_are_detectable(self):
        self.assertNotEqual(sample_value(self.points, 4.5), sample_value(self.points, int(4.5)))
        self.assertNotEqual(0, sample_value(self.points, 18))
        points = [(0, 0), (10, 1)]
        self.assertNotEqual(sample_value(points, 15, 20), sample_value(points, 15, 10))


class AlphaExampleTest(unittest.TestCase):
    def test_equivalent_straight_and_premultiplied_source_over(self):
        cs, a, cd_p = 0.8, 0.5, 0.1
        source_p = cs * a
        self.assertAlmostEqual(0.45, cs * a + cd_p * (1 - a))
        self.assertAlmostEqual(0.45, source_p + cd_p * (1 - a))
        self.assertNotAlmostEqual(0.45, source_p * a + cd_p * (1 - a))


if __name__ == '__main__':
    unittest.main()
