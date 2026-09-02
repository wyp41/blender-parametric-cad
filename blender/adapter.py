"""Single Blender persistence and rebuild integration service."""

from __future__ import annotations

from pathlib import Path

import bpy

from ..core.document import CadDocument
from ..core.evaluator import EvaluationResult, PartEvaluator
from ..core.serialization import dumps, loads
from ..geometry.blender_mesh_backend import BlenderMeshBackend
from .viewport.provenance import clear_face_provenance, set_face_provenance


def load_document_from_scene(scene: bpy.types.Scene) -> CadDocument:
    return loads(scene.parametric_cad_document)


def save_document_to_scene(scene: bpy.types.Scene, document: CadDocument) -> None:
    scene.parametric_cad_document = dumps(document)


def remove_part_geometry(part_id: str) -> None:
    """Remove disposable Blender objects owned by one Part Studio."""

    for item in list(bpy.data.objects):
        if item.get("cad_part_id") == part_id:
            _remove_result_object(item)


def rename_part_geometry(part_id: str, part_name: str) -> None:
    result_object = _find_result_object(part_id)
    if result_object is not None:
        result_object.name = f"{part_name}_Result"
        if result_object.data:
            result_object.data.name = f"{part_name}_Result_Mesh"


def rebuild_part(scene: bpy.types.Scene, part_id: str | None = None) -> EvaluationResult:
    """Replace generated display geometry by evaluating persistent CAD history."""

    document = load_document_from_scene(scene)
    target_id = part_id or document.active_part_id
    part = document.get_part(target_id) if target_id else None
    if part is None:
        return EvaluationResult(False, errors=[])

    result = PartEvaluator(BlenderMeshBackend()).evaluate(part)
    save_document_to_scene(scene, document)
    display = _ensure_collection(scene, "CAD", "DISPLAY")
    result_object = _find_result_object(part.id)

    if result.body is None:
        if result_object is not None:
            _remove_result_object(result_object)
        return result

    result.body.name = f"{part.name}_Result_Mesh"
    if result_object is None:
        result_object = bpy.data.objects.new(f"{part.name}_Result", result.body)
        display.objects.link(result_object)
    else:
        old_mesh = result_object.data
        result_object.data = result.body
        result_object.name = f"{part.name}_Result"
        if old_mesh and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)

    result_object["cad_part_id"] = part.id
    result_object["cad_generated"] = True
    provenance = result.context.face_provenance if result.context else {}
    set_face_provenance(result_object, provenance)
    result_object.update_tag()
    bpy.context.view_layer.update()
    return result


def export_part(
    scene: bpy.types.Scene,
    part_id: str,
    filepath: str,
    file_format: str = "STL",
) -> str:
    """Rebuild and export one Part Studio's generated result object.

    ``file_format`` is one of ``STL``, ``OBJ``, or ``PLY``.  The export is
    isolated to the requested Part Studio even when other Part Studios are
    present in the scene.  A missing extension is added from ``file_format``.
    """

    if not str(filepath).strip():
        raise ValueError("An export filepath is required.")
    format_name = str(file_format or "").upper().lstrip(".")
    if format_name not in {"STL", "OBJ", "PLY"}:
        raise ValueError("Export format must be STL, OBJ, or PLY.")

    result = rebuild_part(scene, part_id)
    if not result.success:
        message = "; ".join(error.message for error in result.errors)
        raise ValueError(message or "Part Studio could not be rebuilt for export.")
    result_object = _find_result_object(part_id)
    if result_object is None:
        raise ValueError(f"Part Studio {part_id} has no generated result body.")

    path = Path(str(filepath))
    if not path.suffix:
        path = path.with_suffix(f".{format_name.lower()}")

    selected_objects = list(bpy.context.selected_objects)
    active_object = bpy.context.view_layer.objects.active
    for item in selected_objects:
        item.select_set(False)
    result_object.select_set(True)
    bpy.context.view_layer.objects.active = result_object
    try:
        operators = {
            "STL": bpy.ops.wm.stl_export,
            "OBJ": bpy.ops.wm.obj_export,
            "PLY": bpy.ops.wm.ply_export,
        }
        status = operators[format_name](
            filepath=str(path),
            export_selected_objects=True,
        )
        if "FINISHED" not in status:
            raise RuntimeError(f"Blender {format_name} export did not finish.")
    finally:
        result_object.select_set(False)
        for item in selected_objects:
            try:
                item.select_set(True)
            except ReferenceError:
                pass
        try:
            bpy.context.view_layer.objects.active = active_object
        except ReferenceError:
            bpy.context.view_layer.objects.active = None
    return str(path)


def _ensure_collection(
    scene: bpy.types.Scene, root_name: str, child_name: str
) -> bpy.types.Collection:
    root = bpy.data.collections.get(root_name)
    if root is None:
        root = bpy.data.collections.new(root_name)
        scene.collection.children.link(root)
    elif root.name not in scene.collection.children:
        scene.collection.children.link(root)

    child = bpy.data.collections.get(child_name)
    if child is None:
        child = bpy.data.collections.new(child_name)
        root.children.link(child)
    elif child.name not in root.children:
        root.children.link(child)

    internal = bpy.data.collections.get("INTERNAL")
    if internal is None:
        internal = bpy.data.collections.new("INTERNAL")
        root.children.link(internal)
    elif internal.name not in root.children:
        root.children.link(internal)
    internal.hide_viewport = True
    internal.hide_render = True
    return child


def _find_result_object(part_id: str) -> bpy.types.Object | None:
    return next(
        (
            item
            for item in bpy.data.objects
            if item.get("cad_generated") and item.get("cad_part_id") == part_id
        ),
        None,
    )


def _remove_result_object(result_object: bpy.types.Object) -> None:
    mesh = result_object.data
    clear_face_provenance(result_object)
    bpy.data.objects.remove(result_object, do_unlink=True)
    if mesh and mesh.users == 0:
        bpy.data.meshes.remove(mesh)
