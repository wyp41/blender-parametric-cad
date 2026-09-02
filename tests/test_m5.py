from __future__ import annotations

import unittest
from math import cos, pi, sin

from blender_parametric_cad.core.evaluator import PartEvaluator
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.core.references import AxisReference
from blender_parametric_cad.core.serialization import document_from_dict, document_to_dict
from blender_parametric_cad.core.transform import Transform
from blender_parametric_cad.features.extrude import ExtrudeFeature
from blender_parametric_cad.features.mirror import MirrorFeature
from blender_parametric_cad.features.revolve import RevolveFeature
from blender_parametric_cad.features.transform import TransformFeature
from blender_parametric_cad.geometry.backend import GeometryBackend
from blender_parametric_cad.sketch.entities import SketchCircle, SketchLine
from blender_parametric_cad.sketch.numeric import set_rectangle
from blender_parametric_cad.sketch.profile import ProfileDetector
from blender_parametric_cad.sketch.plane import SketchPlaneReference
from blender_parametric_cad.sketch.sketch import SketchFeature

from .helpers import rectangle_sketch


class RecordingM5Backend(GeometryBackend):
    def __init__(self, fail_mirror_union: bool = False) -> None:
        self.calls: list[tuple[str, object]] = []
        self.fail_mirror_union = fail_mirror_union
        self.union_count = 0

    def create_extrusion(self, sketch, profile, distance, direction):
        body = {
            "kind": "extrude",
            "origin": sketch.origin,
            "x_axis": sketch.x_axis,
            "y_axis": sketch.y_axis,
            "profile": profile,
            "distance": distance,
            "direction": direction,
        }
        self.calls.append(("extrude", body))
        return body

    def create_extrusion_tool(self, sketch, profile, body, direction):
        tool = {"kind": "through_all", "profile": profile, "body": body}
        self.calls.append(("through_all", tool))
        return tool

    def create_blind_extrusion_tool(self, sketch, profile, distance, direction):
        tool = {"kind": "blind_remove", "profile": profile, "distance": distance}
        self.calls.append(("blind_remove", tool))
        return tool

    def revolve_profile(self, sketch, profile, axis_origin, axis_direction, angle):
        body = {
            "kind": "revolve",
            "origin": sketch.origin,
            "profile": profile,
            "axis_origin": axis_origin,
            "axis_direction": axis_direction,
            "angle": angle,
        }
        self.calls.append(("revolve", body))
        return body

    def boolean_union(self, body, tool):
        self.union_count += 1
        if self.fail_mirror_union and self.union_count >= 2:
            raise ValueError(
                "Boolean Add must produce one connected solid; found 2 components."
            )
        result = {"kind": "union", "body": body, "tool": tool}
        self.calls.append(("union", result))
        return result

    def boolean_difference(self, body, tool):
        result = {"kind": "difference", "body": body, "tool": tool}
        self.calls.append(("difference", result))
        return result

    def transform_body(self, body, transform):
        result = {"kind": "transform", "body": body, "transform": transform}
        self.calls.append(("transform", result))
        return result

    def mirror_tool(self, tool, plane_origin, plane_normal):
        result = {
            "kind": "mirror_tool",
            "tool": tool,
            "plane_origin": plane_origin,
            "plane_normal": plane_normal,
        }
        self.calls.append(("mirror_tool", result))
        return result


def six_line_sketch(name: str = "Guide") -> SketchFeature:
    sketch = SketchFeature.on_plane(name, "XY")
    points = [
        (0.010, 0.000),
        (0.035, 0.000),
        (0.040, 0.008),
        (0.030, 0.018),
        (0.012, 0.018),
        (0.005, 0.008),
    ]
    sketch.entities = [
        SketchLine(
            x1=start[0],
            y1=start[1],
            x2=end[0],
            y2=end[1],
        )
        for start, end in zip(points, points[1:] + points[:1])
    ]
    return sketch


class M5TransformTests(unittest.TestCase):
    def test_transform_moves_downstream_datum_sketch_and_rebuilds_after_edit(self) -> None:
        base = rectangle_sketch()
        new = ExtrudeFeature(sketch_id=base.id, distance=0.020)
        transform = TransformFeature(
            translation=(0.010, 0.002, 0.003),
            rotation=(0.0, -12.0 * pi / 180.0, 0.0),
            dependencies=[new.id],
        )
        guide = SketchFeature.on_plane("Guide", "YZ", offset=0.020)
        set_rectangle(guide, -0.005, -0.005, 0.010, 0.010)
        guide_add = ExtrudeFeature(
            sketch_id=guide.id,
            distance=0.005,
            operation="ADD",
            dependencies=[guide.id, transform.id],
        )
        part = Part(features=[base, new, transform, guide, guide_add])
        backend = RecordingM5Backend()

        first = PartEvaluator(backend).evaluate(part)

        self.assertTrue(first.success)
        transformed = next(value for name, value in backend.calls if name == "transform")
        self.assertEqual(transformed["transform"], Transform(transform.translation, transform.rotation))
        guide_origin = first.context.resolved_planes[guide.id].origin
        self.assertAlmostEqual(guide_origin[0], 0.010 + 0.020 * cos(12.0 * pi / 180.0), places=8)
        self.assertAlmostEqual(guide_origin[1], 0.002, places=8)
        self.assertAlmostEqual(guide_origin[2], 0.003 + 0.020 * sin(12.0 * pi / 180.0), places=8)

        transform.rotation = (0.0, -10.0 * pi / 180.0, 0.0)
        second = PartEvaluator(backend).evaluate(part)

        self.assertTrue(second.success)
        self.assertNotEqual(
            first.context.resolved_planes[guide.id].y_axis,
            second.context.resolved_planes[guide.id].y_axis,
        )

    def test_transform_feature_round_trip_preserves_units_and_values(self) -> None:
        base = rectangle_sketch()
        new = ExtrudeFeature(sketch_id=base.id)
        transform = TransformFeature(
            translation=(0.012, -0.004, 0.003),
            rotation=(0.1, -0.2, 0.3),
            dependencies=[new.id],
        )
        from blender_parametric_cad.core.document import CadDocument

        document = CadDocument(parts=[Part(features=[base, new, transform])])
        restored = document_from_dict(document_to_dict(document)).parts[0]
        value = restored.get_feature(transform.id)
        self.assertIsInstance(value, TransformFeature)
        self.assertEqual(value.translation, transform.translation)
        self.assertEqual(value.rotation, transform.rotation)

    def test_offset_and_mirror_references_round_trip(self) -> None:
        base = rectangle_sketch()
        new = ExtrudeFeature(sketch_id=base.id)
        guide = SketchFeature.on_plane("Guide", "YZ", offset=0.015)
        guide_add = ExtrudeFeature(
            sketch_id=guide.id,
            operation="ADD",
            dependencies=[guide.id, new.id],
        )
        mirror = MirrorFeature(
            source_feature_id=guide_add.id,
            mirror_plane=SketchPlaneReference("DATUM", datum_plane="YZ", offset=0.025),
            dependencies=[guide_add.id],
        )
        from blender_parametric_cad.core.document import CadDocument

        document = CadDocument(parts=[Part(features=[base, new, guide, guide_add, mirror])])
        restored = document_from_dict(document_to_dict(document)).parts[0]
        restored_guide = restored.get_feature(guide.id)
        restored_mirror = restored.get_feature(mirror.id)
        self.assertAlmostEqual(restored_guide.plane_offset, 0.015)
        self.assertEqual(restored_mirror.source_feature_id, guide_add.id)
        self.assertAlmostEqual(restored_mirror.mirror_plane.offset, 0.025)


class M5MirrorAndProfileTests(unittest.TestCase):
    def _mirror_chain(self, backend: GeometryBackend):
        base = rectangle_sketch()
        new = ExtrudeFeature(sketch_id=base.id, distance=0.020)
        guide = six_line_sketch()
        guide_add = ExtrudeFeature(
            name="GuideLeft",
            sketch_id=guide.id,
            distance=0.005,
            operation="ADD",
            dependencies=[guide.id, new.id],
        )
        mirror = MirrorFeature(
            name="GuideRight",
            source_feature_id=guide_add.id,
            dependencies=[guide_add.id],
        )
        result = PartEvaluator(backend).evaluate(
            Part(features=[base, new, guide, guide_add, mirror])
        )
        return result, guide, guide_add, mirror

    def test_six_line_profile_is_closed_and_reaches_add_then_mirror(self) -> None:
        guide = six_line_sketch()
        detected = ProfileDetector().detect(guide)
        self.assertTrue(detected.success)
        self.assertEqual(len(detected.profile.points), 6)

        backend = RecordingM5Backend()
        result, _guide, _source, mirror = self._mirror_chain(backend)
        self.assertTrue(result.success)
        self.assertEqual(mirror.status, "OK")
        self.assertEqual([name for name, _value in backend.calls][-3:], ["extrude", "mirror_tool", "union"])
        self.assertEqual(backend.calls[-2][1]["plane_normal"], (1.0, 0.0, 0.0))

    def test_mirror_references_source_uuid_and_updates_after_source_edit(self) -> None:
        backend = RecordingM5Backend()
        result, guide, source, mirror = self._mirror_chain(backend)
        self.assertTrue(result.success)
        self.assertEqual(mirror.source_feature_id, source.id)
        first_profile = backend.calls[-2][1]["tool"]["profile"]

        guide.entities[0].x2 += 0.004
        guide.entities[1].x1 = guide.entities[0].x2
        second = PartEvaluator(backend).evaluate(result.context.part)
        self.assertTrue(second.success)
        second_profile = backend.calls[-2][1]["tool"]["profile"]
        self.assertNotEqual(first_profile.points, second_profile.points)

    def test_mirror_can_rebuild_an_additive_revolve_source(self) -> None:
        base = rectangle_sketch()
        base_new = ExtrudeFeature(sketch_id=base.id, distance=0.020)
        source_sketch = SketchFeature.on_plane("Revolved guide", "XZ")
        source_sketch.entities = [
            SketchLine(x1=0.010, y1=0.000, x2=0.020, y2=0.000),
            SketchLine(x1=0.020, y1=0.000, x2=0.020, y2=0.010),
            SketchLine(x1=0.020, y1=0.010, x2=0.010, y2=0.010),
            SketchLine(x1=0.010, y1=0.010, x2=0.010, y2=0.000),
        ]
        source = RevolveFeature(
            sketch_id=source_sketch.id,
            axis_reference=AxisReference(axis="Z"),
            angle=pi,
            operation="ADD",
            dependencies=[source_sketch.id, base_new.id],
        )
        mirror = MirrorFeature(source_feature_id=source.id, dependencies=[source.id])
        backend = RecordingM5Backend()
        result = PartEvaluator(backend).evaluate(
            Part(features=[base, base_new, source_sketch, source, mirror])
        )
        self.assertTrue(result.success)
        self.assertEqual(
            [name for name, _value in backend.calls][-4:],
            ["union", "revolve", "mirror_tool", "union"],
        )

    def test_mirror_add_failure_keeps_previous_body_and_blocks_downstream(self) -> None:
        backend = RecordingM5Backend(fail_mirror_union=True)
        result, _guide, _source, mirror = self._mirror_chain(backend)
        self.assertFalse(result.success)
        self.assertEqual(mirror.status, "ERROR")
        self.assertIn("connected solid", mirror.error_message)
        self.assertEqual(result.body["kind"], "union")

    def test_remove_through_all_accepts_multiple_independent_circles(self) -> None:
        base = rectangle_sketch()
        new = ExtrudeFeature(sketch_id=base.id, distance=0.020)
        holes = SketchFeature.on_feature_plane("Holes", new.id)
        holes.entities = [
            SketchCircle(cx=0.020, cy=0.020, radius=0.004),
            SketchCircle(cx=0.060, cy=0.030, radius=0.004),
        ]
        remove = ExtrudeFeature(
            sketch_id=holes.id,
            operation="REMOVE",
            depth_mode="THROUGH_ALL",
            dependencies=[holes.id, new.id],
        )
        backend = RecordingM5Backend()
        result = PartEvaluator(backend).evaluate(Part(features=[base, new, holes, remove]))
        self.assertTrue(result.success)
        tool = next(value for name, value in backend.calls if name == "through_all")
        self.assertEqual(len(tool["profile"].loops), 2)

    def test_magazine_single_body_history_uses_transform_mirror_and_holes(self) -> None:
        base = rectangle_sketch()
        base_new = ExtrudeFeature(name="Base trough", sketch_id=base.id, distance=0.020)

        wall = SketchFeature.on_plane("Bottom wall", "XY")
        set_rectangle(wall, -0.035, -0.020, 0.070, 0.040)
        wall_add = ExtrudeFeature(
            name="Bottom wall ADD",
            sketch_id=wall.id,
            distance=0.004,
            operation="ADD",
            dependencies=[wall.id, base_new.id],
        )

        outlet = SketchFeature.on_feature_plane("Outlet", base_new.id)
        outlet.entities = [SketchCircle(cx=0.0, cy=0.0, radius=0.004)]
        outlet_remove = ExtrudeFeature(
            name="Outlet REMOVE",
            sketch_id=outlet.id,
            operation="REMOVE",
            depth_mode="THROUGH_ALL",
            dependencies=[outlet.id, wall_add.id],
        )

        transform = TransformFeature(
            name="Transform1",
            translation=(0.010, 0.0, 0.002),
            rotation=(0.0, -12.0 * pi / 180.0, 0.0),
            dependencies=[outlet_remove.id],
        )
        guide = six_line_sketch("Left inclined guide")
        guide.plane_reference = guide.plane_reference.__class__(
            "DATUM", datum_plane="YZ", offset=0.015
        )
        guide_add = ExtrudeFeature(
            name="Left guide ADD",
            sketch_id=guide.id,
            distance=0.004,
            operation="ADD",
            dependencies=[guide.id, transform.id],
        )
        mirror = MirrorFeature(
            name="Right guide MIRROR",
            source_feature_id=guide_add.id,
            dependencies=[guide_add.id],
        )
        holes = SketchFeature.on_plane("Guide holes", "YZ", offset=0.015)
        holes.entities = [
            SketchCircle(cx=0.015, cy=0.006, radius=0.002),
            SketchCircle(cx=0.015, cy=-0.006, radius=0.002),
        ]
        holes_remove = ExtrudeFeature(
            name="Guide holes THROUGH_ALL",
            sketch_id=holes.id,
            operation="REMOVE",
            depth_mode="THROUGH_ALL",
            dependencies=[holes.id, mirror.id],
        )

        part = Part(
            features=[
                base,
                base_new,
                wall,
                wall_add,
                outlet,
                outlet_remove,
                transform,
                guide,
                guide_add,
                mirror,
                holes,
                holes_remove,
            ]
        )
        backend = RecordingM5Backend()
        result = PartEvaluator(backend).evaluate(part)

        self.assertTrue(result.success)
        self.assertEqual(
            [feature.status for feature in part.features], ["OK"] * len(part.features)
        )
        self.assertEqual(result.body["kind"], "difference")
        self.assertEqual(
            [name for name, _value in backend.calls].count("mirror_tool"), 1
        )
        self.assertEqual(
            [name for name, _value in backend.calls].count("through_all"), 2
        )


if __name__ == "__main__":
    unittest.main()
