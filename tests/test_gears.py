"""Checks for printable example profiles, dimensions, and input rejection."""
from math import hypot, pi
import unittest

from blender_parametric_cad.sketch.gears import add_outline, internal_outline, rack_outline, spur_outline
from blender_parametric_cad.sketch.profile import ProfileDetector
from blender_parametric_cad.sketch.sketch import SketchFeature


class GearProfileTests(unittest.TestCase):
    def test_external_and_internal_reference_dimensions(self):
        for teeth, generator, low, high in ((20, spur_outline, .0175, .022),
                                            (60, internal_outline, .058, .0625)):
            points = generator(.002, teeth, backlash=.00015)
            self.assertAlmostEqual(min(hypot(*p) for p in points), low)
            self.assertAlmostEqual(max(hypot(*p) for p in points), high)
            sketch = SketchFeature.on_plane('Gear', 'XY')
            add_outline(sketch, points)
            result = ProfileDetector().detect(sketch)
            self.assertTrue(result.success, result.message)

    def test_rack_pitch_length_and_tooth_height(self):
        points = rack_outline(.002, 16, backlash=.00015)
        self.assertAlmostEqual(max(p[0] for p in points)-min(p[0] for p in points), 32*pi/1000)
        self.assertAlmostEqual(max(p[1] for p in points), .002)
        sketch = SketchFeature.on_plane('Rack', 'XY')
        add_outline(sketch, points)
        self.assertTrue(ProfileDetector().detect(sketch).success)

    def test_unsupported_or_nonfinite_inputs_are_rejected(self):
        for arguments in ((0, 20), (.002, 12), (.002, 20.5), (float('nan'), 20)):
            with self.assertRaises(ValueError):
                spur_outline(*arguments)
        with self.assertRaises(ValueError):
            rack_outline(.002, 20, backlash=.01)
        with self.assertRaises(ValueError):
            spur_outline(.002, 20, pressure_angle=pi/18)


if __name__ == '__main__':
    unittest.main()
