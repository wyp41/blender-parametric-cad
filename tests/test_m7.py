"""M7 derived planar references without Blender topology persistence."""

from __future__ import annotations

import unittest
from math import radians
from types import SimpleNamespace

from blender_parametric_cad.core.document import CadDocument
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.core.serialization import document_to_dict, dumps, loads
from blender_parametric_cad.core.transform import IDENTITY_MATRIX
from blender_parametric_cad.features.transform import TransformFeature
from blender_parametric_cad.sketch.planar_faces import (
    PlanarFaceResolver,
    derived_reference_status,
    propagate_planes,
    publish_derived_candidates,
)
from blender_parametric_cad.sketch.plane import (
    DerivedPlaneReference,
    PlaneResolutionError,
    PlaneResolver,
    RegionHint,
)
from blender_parametric_cad.sketch.sketch import SketchFeature


def polygon_mesh(polygons):
    vertices, faces = [], []
    for index, (points, normal) in enumerate(polygons):
        vertex_ids = list(range(len(vertices), len(vertices) + len(points)))
        vertices.extend(SimpleNamespace(co=point) for point in points)
        faces.append(SimpleNamespace(index=index, vertices=vertex_ids, normal=normal))
    return SimpleNamespace(vertices=vertices, polygons=faces)


def context(mesh):
    return SimpleNamespace(
        current_body=mesh,
        semantic_planes={},
        face_provenance={},
        frame_matrix=IDENTITY_MATRIX,
    )


def square(x, y, z=0.0, size=1.0):
    return (
        [(x, y, z), (x + size, y, z), (x + size, y + size, z), (x, y + size, z)],
        (0.0, 0.0, 1.0),
    )


class DerivedPlanarReferenceTests(unittest.TestCase):
    def test_split_region_has_one_reference_and_survives_polygon_repartition(self):
        first = context(polygon_mesh([
            ([(0, 0, 0), (1, 0, 0), (1, 1, 0)], (0, 0, 1)),
            ([(0, 0, 0), (1, 1, 0), (0, 1, 0)], (0, 0, 1)),
        ]))
        publish_derived_candidates(first, "boolean-1")
        resolver = PlanarFaceResolver()
        reference = resolver.resolve_polygon(0, first)
        self.assertEqual(reference.reference_type, "DERIVED_PLANE")
        self.assertEqual(reference, resolver.resolve_polygon(1, first))

        second = context(polygon_mesh([square(0, 0, 0, 1.0)]))
        publish_derived_candidates(second, "boolean-1")
        resolved = PlaneResolver().resolve(reference, second)
        self.assertEqual(resolved.normal, (0.0, 0.0, 1.0))
        self.assertNotIn("polygon_index", dumps(
            CadDocument(parts=[])
        ))

    def test_parallel_and_coplanar_regions_use_offset_and_region_hint(self):
        current = context(polygon_mesh([
            square(0, 0, 0, .01),
            square(0, 0, .02, .01),
            square(.05, 0, 0, .01),
        ]))
        publish_derived_candidates(current, "boolean-2")
        resolver = PlanarFaceResolver()
        first = resolver.resolve_polygon(0, current)
        parallel = resolver.resolve_polygon(1, current)
        other_region = resolver.resolve_polygon(2, current)
        self.assertNotEqual(first.local_offset, parallel.local_offset)
        self.assertNotEqual(first.region_hint, other_region.region_hint)
        self.assertNotEqual(
            PlaneResolver().resolve(first, current).origin,
            PlaneResolver().resolve(other_region, current).origin,
        )

        ambiguous = type(first)(
            producer_feature_id=first.producer_feature_id,
            local_normal=first.local_normal,
            local_offset=first.local_offset,
            source_feature_ids=first.source_feature_ids,
            region_hint=None,
        )
        _, status = derived_reference_status(
            ambiguous, current.derived_plane_candidates["boolean-2"]
        )
        self.assertEqual(status, "AMBIGUOUS")

    def test_serialization_preserves_signature_but_never_runtime_indices(self):
        current = context(polygon_mesh([square(0, 0, 0, .02)]))
        publish_derived_candidates(current, "boolean-3", ("source-feature",))
        reference = PlanarFaceResolver().resolve_polygon(0, current)
        sketch = SketchFeature(name="Derived Sketch", plane_reference=reference)
        document = CadDocument(
            parts=[Part(id="part-1", name="Part", features=[sketch])]
        )
        encoded = dumps(document)
        self.assertNotIn("polygon_index", encoded)
        self.assertNotIn("face_index", encoded)
        self.assertNotIn("edge_index", encoded)
        restored = loads(encoded).parts[0].features[0].plane_reference
        self.assertEqual(restored, reference)
        self.assertEqual(restored.source_feature_ids, ("boolean-3", "source-feature"))

    def test_transform_moves_runtime_plane_without_changing_local_identity(self):
        current = context(polygon_mesh([square(0, 0, 0, .02)]))
        publish_derived_candidates(current, "boolean-4")
        reference = PlanarFaceResolver().resolve_polygon(0, current)
        transform = TransformFeature(rotation=(0.0, radians(-12.0), 0.0))
        before = reference.local_normal, reference.local_offset
        propagate_planes(transform, current)
        resolved = PlaneResolver().resolve(reference, current)
        self.assertEqual(before, (reference.local_normal, reference.local_offset))
        self.assertNotEqual(resolved.normal, (0.0, 0.0, 1.0))

    def test_missing_reference_is_explicit(self):
        current = context(polygon_mesh([]))
        publish_derived_candidates(current, "boolean-5")
        with self.assertRaises(PlaneResolutionError) as raised:
            PlaneResolver().resolve(
                DerivedPlaneReference("boolean-5", (0, 0, 1), 0.0),
                current,
            )
        self.assertIn("missing", str(raised.exception).lower())


if __name__ == "__main__":
    unittest.main()
