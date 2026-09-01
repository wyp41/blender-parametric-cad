"""Single Blender persistence and rebuild integration service."""

from __future__ import annotations

import bpy

from ..core.document import CadDocument
from ..core.evaluator import EvaluationResult, PartEvaluator
from ..core.serialization import dumps, loads
from ..geometry.blender_mesh_backend import BlenderMeshBackend


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
    result_object.update_tag()
    bpy.context.view_layer.update()
    return result


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
    bpy.data.objects.remove(result_object, do_unlink=True)
    if mesh and mesh.users == 0:
        bpy.data.meshes.remove(mesh)
