"""Blender 5.1 M8.1 integration validation for persistent straight edges."""

from __future__ import annotations

import math
import json
import sys
import tempfile
from pathlib import Path

import bpy
import bmesh

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import blender_parametric_cad
from blender_parametric_cad.blender.adapter import (
    load_document_from_scene,
    rebuild_part,
    save_document_to_scene,
)
from blender_parametric_cad.blender.viewport.provenance import (
    clear_runtime_caches,
    get_edge_candidates,
)
from blender_parametric_cad.core.document import CadDocument
from blender_parametric_cad.core.part import delete_feature
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.core.references import EdgeReference
from blender_parametric_cad.features.chamfer import ChamferFeature
from blender_parametric_cad.features.extrude import ExtrudeFeature
from blender_parametric_cad.features.fillet import FilletFeature
from blender_parametric_cad.features.transform import TransformFeature
from blender_parametric_cad.sketch.entities import SketchLine
from blender_parametric_cad.sketch.sketch import SketchFeature


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _clear_scene() -> None:
    clear_runtime_caches()
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def _rectangle(x0: float, y0: float, x1: float, y1: float) -> list[SketchLine]:
    return [
        SketchLine(x1=x0, y1=y0, x2=x1, y2=y0),
        SketchLine(x1=x1, y1=y0, x2=x1, y2=y1),
        SketchLine(x1=x1, y1=y1, x2=x0, y2=y1),
        SketchLine(x1=x0, y1=y1, x2=x0, y2=y0),
    ]


def _result_object(part_id: str):
    return next(
        item
        for item in bpy.data.objects
        if item.get("cad_generated") and item.get("cad_part_id") == part_id
    )


def _rebuild(document: CadDocument, part_id: str, allow_failure: bool = False):
    scene = bpy.context.scene
    save_document_to_scene(scene, document)
    result = rebuild_part(scene, part_id)
    if not result.success and not allow_failure:
        details = "; ".join(error.message for error in result.errors)
        raise AssertionError(f"Rebuild failed: {details}")
    restored = load_document_from_scene(scene)
    return restored, restored.get_part(part_id), result


def _base(width: float = 0.080, height: float = 0.050, depth: float = 0.020):
    _clear_scene()
    document = CadDocument()
    part = Part(name="M8.1 Part")
    sketch = SketchFeature.on_plane("Sketch001", "XY")
    sketch.entities = _rectangle(0.0, 0.0, width, height)
    extrude = ExtrudeFeature(
        name="Extrude001",
        sketch_id=sketch.id,
        distance=depth,
        operation="NEW",
        depth_mode="BLIND",
    )
    part.features = [sketch, extrude]
    document.add_part(part)
    document, part, result = _rebuild(document, part.id)
    return document, part, part.features[0], part.features[1], result


def _candidates(part_id: str):
    return list(get_edge_candidates(_result_object(part_id)).values())


def _semantic_candidates(part_id: str):
    return [candidate for candidate in _candidates(part_id) if candidate.semantic_reference]


def _top_edges(part_id: str, z: float):
    return [
        candidate
        for candidate in _semantic_candidates(part_id)
        if all(abs(point[2] - z) <= 1e-8 for point in (candidate.start, candidate.end))
    ]


def _vertical_edges(part_id: str, depth: float):
    return [
        candidate
        for candidate in _semantic_candidates(part_id)
        if abs(candidate.length - depth) <= 1e-8
        and abs(abs(candidate.direction[2]) - 1.0) <= 1e-8
    ]


def _mesh_stats(part_id: str) -> dict[str, int]:
    mesh = _result_object(part_id).data
    _check(len(mesh.vertices) > 0 and len(mesh.polygons) > 0, "Generated mesh is empty.")
    body = bmesh.new()
    try:
        body.from_mesh(mesh)
        _check(not any(edge.is_wire for edge in body.edges), "Generated mesh contains a wire edge.")
        _check(
            not any(not edge.is_manifold for edge in body.edges),
            "Generated bevel mesh contains a non-manifold edge.",
        )
        return {
            "vertices": len(body.verts),
            "edges": len(body.edges),
            "faces": len(body.faces),
        }
    finally:
        body.free()


def _assert_runtime_cleanup(part_id: str) -> None:
    generated = [
        item
        for item in bpy.data.objects
        if item.get("cad_generated")
    ]
    _check(len(generated) == 1, "Repeated rebuild left duplicate result objects.")
    result_object = generated[0]
    _check(
        result_object.get("cad_part_id") == part_id,
        "Runtime cleanup retained a result from another Part Studio.",
    )
    candidates = get_edge_candidates(result_object)
    _check(
        len(candidates) == len(result_object.data.edges),
        "Runtime edge candidate cache does not match the current mesh.",
    )
    _check(
        all(0 <= index < len(result_object.data.edges) for index in candidates),
        "Runtime edge cache contains a stale mesh index.",
    )
    _check(
        not [item for item in bpy.data.objects if item.name.startswith("CAD_Boolean_")],
        "Boolean helper objects leaked into the scene.",
    )
    _check(
        not [
            item
            for item in bpy.data.meshes
            if item.name.startswith("CAD_ThroughAll_Cutter")
        ],
        "Through-All cutter mesh leaked into the scene.",
    )


def _assert_semantic_serialization() -> None:
    raw = getattr(bpy.context.scene, "parametric_cad_document", "")
    _check(raw, "CAD document JSON was not written to the scene.")
    json.loads(raw)
    for forbidden in ("mesh_edge_index", "edge_index", "bmesh_edge", "candidate_id"):
        _check(forbidden not in raw, f"Runtime edge field {forbidden!r} was serialized.")


def _add_edge_feature(document, part, feature):
    part.add_feature(feature)
    return _rebuild(document, part.id)


def _resize(sketch, width: float, height: float) -> None:
    _set_rectangle(sketch, 0.0, 0.0, width, height)


def _set_rectangle(sketch, x0: float, y0: float, x1: float, y1: float) -> None:
    points = (
        (x0, y0, x1, y0),
        (x1, y0, x1, y1),
        (x1, y1, x0, y1),
        (x0, y1, x0, y0),
    )
    _check(len(sketch.entities) == len(points), "Resize requires the original four SketchLines.")
    for entity, (x1, y1, x2, y2) in zip(sketch.entities, points):
        _check(isinstance(entity, SketchLine), "Resize requires SketchLine entities.")
        entity.x1, entity.y1 = x1, y1
        entity.x2, entity.y2 = x2, y2


def _test_simple_chamfer() -> None:
    document, part, _sketch, extrude, result = _base()
    top = _top_edges(part.id, extrude.distance)
    _check(len(top) == 4, f"Expected four top edges, got {len(top)}.")
    reference = top[0].semantic_reference
    base_stats = _mesh_stats(part.id)
    document, part, result = _add_edge_feature(
        document,
        part,
        ChamferFeature(
            name="Chamfer001",
            edge_references=[reference],
            distance=0.002,
        ),
    )
    _check(result.success and part.features[-1].status == "OK", "Real Chamfer did not rebuild.")
    _check(_mesh_stats(part.id)["vertices"] > base_stats["vertices"], "Chamfer did not change the mesh.")

    sketch = part.features[0]
    _resize(sketch, 0.100, 0.050)
    document, part, result = _rebuild(document, part.id)
    _check(result.success and part.features[-1].status == "OK", "Chamfer lost its edge after width edit.")
    print("M8.1 Chamfer: OK")


def _test_simple_fillet() -> None:
    document, part, _sketch, extrude, result = _base()
    vertical = _vertical_edges(part.id, extrude.distance)
    _check(len(vertical) == 4, f"Expected four vertical edges, got {len(vertical)}.")
    reference = vertical[0].semantic_reference
    base_stats = _mesh_stats(part.id)
    document, part, result = _add_edge_feature(
        document,
        part,
        FilletFeature(
            name="Fillet001",
            edge_references=[reference],
            radius=0.002,
        ),
    )
    _check(result.success and part.features[-1].status == "OK", "Real Fillet did not rebuild.")
    _check(_mesh_stats(part.id)["vertices"] > base_stats["vertices"], "Fillet did not change the mesh.")

    sketch = part.features[0]
    _resize(sketch, 0.100, 0.050)
    document, part, result = _rebuild(document, part.id)
    _check(result.success and part.features[-1].status == "OK", "Fillet lost its edge after width edit.")
    print("M8.1 Fillet: OK")


def _test_multiple_edges() -> None:
    document, part, _sketch, extrude, result = _base()
    vertical = _vertical_edges(part.id, extrude.distance)
    _check(len(vertical) == 4, f"Expected four vertical edges, got {len(vertical)}.")
    document, part, result = _add_edge_feature(
        document,
        part,
        ChamferFeature(
            name="Chamfer001",
            edge_references=[item.semantic_reference for item in vertical],
            distance=0.002,
        ),
    )
    _check(result.success and part.features[-1].status == "OK", "Multi-edge Chamfer failed.")
    _resize(part.features[0], 0.100, 0.060)
    document, part, result = _rebuild(document, part.id)
    _check(result.success and part.features[-1].status == "OK", "Multi-edge references did not rebuild.")
    print("M8.1 Multi-edge Chamfer: OK")


def _test_transform() -> None:
    document, part, _sketch, extrude, result = _base()
    transform = TransformFeature(
        name="Transform001",
        rotation=(0.0, math.radians(-12.0), 0.0),
        dependencies=[extrude.id],
    )
    document, part, result = _add_edge_feature(document, part, transform)
    transformed_edges = [
        candidate
        for candidate in _semantic_candidates(part.id)
        if abs(candidate.length - extrude.distance) <= 1e-8
    ]
    _check(transformed_edges, "No transformed straight edge candidates were published.")
    reference = transformed_edges[0].semantic_reference
    chamfer = ChamferFeature(name="Chamfer001", edge_references=[reference], distance=0.002)
    document, part, result = _add_edge_feature(document, part, chamfer)
    _check(result.success and part.features[-1].status == "OK", "Transformed Chamfer failed.")
    part.features[2].rotation = (0.0, math.radians(-8.0), 0.0)
    document, part, result = _rebuild(document, part.id)
    _check(result.success and part.features[-1].status == "OK", "Transform edit invalidated the edge reference.")
    print("M8.1 Transform: OK")


def _test_boolean_derived_edge() -> None:
    document, part, _sketch, _extrude, result = _base()
    cutter = SketchFeature.on_plane("CutterSketch", "XY")
    cutter.entities = _rectangle(0.025, 0.015, 0.055, 0.035)
    cut = ExtrudeFeature(
        name="Remove001",
        sketch_id=cutter.id,
        distance=0.020,
        operation="REMOVE",
        depth_mode="THROUGH_ALL",
    )
    part.features.extend((cutter, cut))
    document, part, result = _rebuild(document, part.id)
    _check(result.success, "Boolean Remove failed before edge selection.")
    derived = [
        candidate
        for candidate in _semantic_candidates(part.id)
        if candidate.semantic_reference.producer_feature_id == cut.id
        and abs(candidate.length - 0.020) <= 1e-7
        and 0.020 < candidate.midpoint[0] < 0.060
        and 0.010 < candidate.midpoint[1] < 0.040
    ]
    _check(derived, "No straight Boolean-derived edge candidate was published.")
    reference = derived[0].semantic_reference
    chamfer = ChamferFeature(name="Chamfer001", edge_references=[reference], distance=0.002)
    document, part, result = _add_edge_feature(document, part, chamfer)
    _check(result.success and part.features[-1].status == "OK", "Boolean-derived Chamfer failed.")

    cutter = part.features[2]
    _set_rectangle(cutter, 0.020, 0.012, 0.060, 0.038)
    document, part, result = _rebuild(document, part.id)
    _check(
        result.success and part.features[-1].status == "OK",
        "Boolean-derived edge did not follow cutter dimensions.",
    )
    print("M8.1 Boolean-derived edge: OK")


def _test_missing_ambiguous_and_lifecycle() -> None:
    document, part, _sketch, extrude, result = _base()
    top = _top_edges(part.id, extrude.distance)
    reference = top[0].semantic_reference
    chamfer = ChamferFeature(name="Chamfer001", edge_references=[reference], distance=0.002)
    document, part, result = _add_edge_feature(document, part, chamfer)
    _check(result.success, "Lifecycle setup Chamfer failed.")

    sketch = part.features[0]
    original_entities = list(sketch.entities)
    sketch.entities = [
        entity
        for entity in original_entities
        if entity.id not in reference.source_entity_ids
    ]
    document, part, result = _rebuild(document, part.id, allow_failure=True)
    _check(not result.success and part.features[-1].status == "BLOCKED", "Missing edge did not block.")

    part.features[0].entities = original_entities
    document, part, result = _rebuild(document, part.id)
    _check(result.success and part.features[-1].status == "OK", "Missing edge did not recover.")

    part.features[-1].suppressed = True
    document, part, result = _rebuild(document, part.id)
    _check(result.success and part.features[-1].status == "SUPPRESSED", "Chamfer suppression failed.")
    part.features[-1].suppressed = False
    part.rollback_index = 1
    document, part, result = _rebuild(document, part.id)
    _check(result.success and part.features[-1].status == "NOT_EVALUATED", "Chamfer rollback failed.")
    part.rollback_index = None
    document, part, result = _rebuild(document, part.id)
    _check(result.success and part.features[-1].status == "OK", "Chamfer roll-forward failed.")

    feature_id = part.features[-1].id
    deleted = delete_feature(part, feature_id)
    _check(any(feature.id == feature_id for feature in deleted), "Fillet/Chamfer delete missed the feature.")
    document, part, result = _rebuild(document, part.id)
    _check(result.success, "Rebuild after edge-feature delete failed.")
    print("M8.1 Missing/rollback/suppression/delete: OK")


def _test_ambiguous_reference() -> None:
    document, part, _sketch, extrude, result = _base()
    candidate = _top_edges(part.id, extrude.distance)[0]
    source = candidate.semantic_reference
    ambiguous = EdgeReference(
        producer_feature_id=source.producer_feature_id,
        role=source.role,
        adjacent_plane_refs=(source.adjacent_plane_refs[0], None),
        source_entity_ids=(),
        local_signature=None,
    )
    part.add_feature(
        ChamferFeature(name="AmbiguousChamfer", edge_references=[ambiguous], distance=0.002)
    )
    document, part, result = _rebuild(document, part.id, allow_failure=True)
    _check(not result.success, "Ambiguous edge reference unexpectedly rebuilt.")
    _check(part.features[-1].status == "BLOCKED", "Ambiguous edge did not become BLOCKED.")
    _check("ambiguous" in part.features[-1].error_message.lower(), "Missing ambiguous diagnostic.")
    print("M8.1 Ambiguous edge: BLOCKED with diagnostic")


def _test_runtime_cleanup() -> None:
    document, part, _sketch, extrude, result = _base()
    reference = _vertical_edges(part.id, extrude.distance)[0].semantic_reference
    part.add_feature(ChamferFeature(name="Chamfer001", edge_references=[reference], distance=0.002))
    document, part, result = _rebuild(document, part.id)
    _check(result.success, "Runtime cleanup Chamfer setup failed.")
    for distance in (0.001, 0.003, 0.002, 0.001):
        part.features[-1].distance = distance
        document, part, result = _rebuild(document, part.id)
        _check(result.success and part.features[-1].status == "OK", "Chamfer edit failed.")
        _assert_runtime_cleanup(part.id)

    document, part, _sketch, extrude, result = _base()
    reference = _vertical_edges(part.id, extrude.distance)[0].semantic_reference
    part.add_feature(FilletFeature(name="Fillet001", edge_references=[reference], radius=0.002))
    document, part, result = _rebuild(document, part.id)
    _check(result.success, "Runtime cleanup Fillet setup failed.")
    for radius in (0.001, 0.003, 0.002, 0.001):
        part.features[-1].radius = radius
        document, part, result = _rebuild(document, part.id)
        _check(result.success and part.features[-1].status == "OK", "Fillet edit failed.")
        _assert_runtime_cleanup(part.id)
    print("M8.1 Runtime cleanup: OK")


def _test_save_reload() -> None:
    document, part, _sketch, extrude, result = _base()
    reference = _vertical_edges(part.id, extrude.distance)[0].semantic_reference
    feature = FilletFeature(name="Fillet001", edge_references=[reference], radius=0.002)
    document, part, result = _add_edge_feature(document, part, feature)
    _check(result.success, "Save/reload setup Fillet failed.")
    path = str(Path(tempfile.gettempdir()) / "blender_parametric_cad_m8_1.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    _assert_semantic_serialization()
    restored = load_document_from_scene(bpy.context.scene)
    restored_part = restored.active_part
    _check(restored_part is not None, "No active Part Studio after reload.")
    _check(restored_part.features[-1].feature_type == "FILLET", "Fillet was not restored.")
    print(f"M8.1 Save serialization: OK ({path})")


def main() -> None:
    _clear_scene()
    if not hasattr(bpy.types.Scene, "parametric_cad_document"):
        blender_parametric_cad.register()
    _test_simple_chamfer()
    _test_simple_fillet()
    _test_multiple_edges()
    _test_transform()
    _test_boolean_derived_edge()
    _test_missing_ambiguous_and_lifecycle()
    _test_ambiguous_reference()
    _test_runtime_cleanup()
    _test_save_reload()
    print("BLENDER_PARAMETRIC_CAD_M8_1_CORE_VALIDATION_OK")


main()
