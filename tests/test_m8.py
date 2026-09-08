from __future__ import annotations

import unittest

from blender_parametric_cad.core.evaluator import PartEvaluator
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.core.references import EdgeReference, EdgeSignature
from blender_parametric_cad.core.serialization import document_to_dict, edge_reference_from_dict
from blender_parametric_cad.features.chamfer import ChamferFeature
from blender_parametric_cad.features.extrude import ExtrudeFeature
from blender_parametric_cad.features.fillet import FilletFeature
from blender_parametric_cad.geometry.backend import GeometryBackend
from blender_parametric_cad.sketch.edges import PersistentEdgeResolver

from .helpers import rectangle_sketch


class _Vertex:
    def __init__(self, co):
        self.co = co


class _Polygon:
    def __init__(self, index, vertices, normal):
        self.index = index
        self.vertices = vertices
        self.normal = normal


class _BoxMesh:
    def __init__(self, width=0.080, height=0.050, depth=0.020):
        self.vertices = [
            _Vertex((0.0, 0.0, 0.0)),
            _Vertex((width, 0.0, 0.0)),
            _Vertex((width, height, 0.0)),
            _Vertex((0.0, height, 0.0)),
            _Vertex((0.0, 0.0, depth)),
            _Vertex((width, 0.0, depth)),
            _Vertex((width, height, depth)),
            _Vertex((0.0, height, depth)),
        ]
        polygons = (
            ((0, 3, 2, 1), (0.0, 0.0, -1.0)),
            ((4, 5, 6, 7), (0.0, 0.0, 1.0)),
            ((0, 1, 5, 4), (0.0, -1.0, 0.0)),
            ((1, 2, 6, 5), (1.0, 0.0, 0.0)),
            ((2, 3, 7, 6), (0.0, 1.0, 0.0)),
            ((3, 0, 4, 7), (-1.0, 0.0, 0.0)),
        )
        self.polygons = [_Polygon(index, vertices, normal) for index, (vertices, normal) in enumerate(polygons)]


class _EdgeRecordingBackend(GeometryBackend):
    def create_extrusion(self, *_args):
        return _BoxMesh()

    def chamfer_edges(self, body, resolved_edges, distance):
        self.last_operation = ("CHAMFER", resolved_edges, distance)
        return body

    def fillet_edges(self, body, resolved_edges, radius):
        self.last_operation = ("FILLET", resolved_edges, radius)
        return body


class PersistentEdgeTests(unittest.TestCase):
    def test_direction_sign_is_canonical_and_json_has_no_mesh_index(self):
        first = EdgeSignature((1.0, 0.0, 0.0), (0.0, 2.0, 3.0), (1.0, 2.0, 3.0), 2.0)
        second = EdgeSignature((-1.0, 0.0, 0.0), (0.0, 2.0, 3.0), (1.0, 2.0, 3.0), 2.0)
        self.assertEqual(first, second)
        reference = EdgeReference("producer", local_signature=first)
        payload = reference.to_dict()
        self.assertNotIn("mesh_edge_index", payload)
        self.assertNotIn("edge_index", payload)
        with self.assertRaises(ValueError):
            edge_reference_from_dict({"producer_feature_id": "producer", "edge_index": 3})

    def _base(self):
        sketch = rectangle_sketch()
        extrude = ExtrudeFeature(sketch_id=sketch.id, distance=0.020)
        part = Part(features=[sketch, extrude])
        backend = _EdgeRecordingBackend()
        result = PartEvaluator(backend).evaluate(part)
        self.assertTrue(result.success)
        references = [
            candidate.semantic_reference
            for candidate in result.context.edge_candidates.values()
            if candidate.semantic_reference is not None
        ]
        self.assertEqual(len(references), 12)
        return part, extrude, backend, references

    def test_runtime_cache_resolves_all_box_edges(self):
        _part, _extrude, backend, references = self._base()
        self.assertEqual(len(set(references)), 12)
        context = PartEvaluator(backend).evaluate(_part).context
        resolved = PersistentEdgeResolver().resolve(references[0], context)
        self.assertEqual(resolved.mesh_edge_index, 0)

    def test_chamfer_and_fillet_use_persistent_edges(self):
        for feature_class, operation in ((ChamferFeature, "CHAMFER"), (FilletFeature, "FILLET")):
            with self.subTest(operation=operation):
                part, _extrude, backend, references = self._base()
                feature = feature_class(edge_references=[references[0]], **{
                    "distance": 0.002
                } if feature_class is ChamferFeature else {"radius": 0.002})
                part.add_feature(feature)
                result = PartEvaluator(backend).evaluate(part)
                self.assertTrue(result.success)
                self.assertEqual(feature.status, "OK")
                self.assertEqual(backend.last_operation[0], operation)
                self.assertEqual(len(backend.last_operation[1]), 1)

    def test_missing_and_ambiguous_edges_block_without_guessing(self):
        part, extrude, backend, references = self._base()
        missing_plane = references[0].adjacent_plane_refs[0]
        missing = EdgeReference(
            extrude.id,
            adjacent_plane_refs=(
                missing_plane.__class__(
                    "FACE",
                    None,
                    extrude.id,
                    "NOT_A_REAL_PLANE",
                    None,
                ),
                None,
            ),
            local_signature=references[0].local_signature,
        )
        feature = ChamferFeature(edge_references=[missing], distance=0.002)
        part.add_feature(feature)
        result = PartEvaluator(backend).evaluate(part)
        self.assertFalse(result.success)
        self.assertEqual(feature.status, "BLOCKED")
        self.assertIn("missing", feature.error_message.lower())

        part, extrude, backend, references = self._base()
        ambiguous = EdgeReference(
            extrude.id,
            adjacent_plane_refs=(references[0].adjacent_plane_refs[0], None),
        )
        feature = FilletFeature(edge_references=[ambiguous], radius=0.002)
        part.add_feature(feature)
        result = PartEvaluator(backend).evaluate(part)
        self.assertFalse(result.success)
        self.assertEqual(feature.status, "BLOCKED")
        self.assertIn("ambiguous", feature.error_message.lower())

    def test_feature_document_contains_semantics_only(self):
        part, _extrude, _backend, references = self._base()
        part.add_feature(ChamferFeature(edge_references=references[:2], distance=0.002))
        data = document_to_dict(type("Document", (), {"active_part_id": part.id, "parts": [part]})())
        serialized = str(data)
        self.assertNotIn("mesh_edge_index", serialized)
        self.assertNotIn("edge_index", serialized)
        self.assertIn("local_signature", serialized)


if __name__ == "__main__":
    unittest.main()
