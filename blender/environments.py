"""Native Scene roles, stable source Collections, and linked Assembly display."""

from __future__ import annotations

import bpy
from mathutils import Matrix

PART_STUDIO = "PART_STUDIO"
ASSEMBLY = "ASSEMBLY"


def scene_role(scene) -> str:
    """Treat untagged legacy Scenes as Part Studio contexts."""
    return scene.get("cad_scene_role", PART_STUDIO)


def part_studio_scene():
    """Resolve the stable authoring Scene regardless of the active window."""
    scene = next((item for item in bpy.data.scenes if item.get("cad_scene_role") == PART_STUDIO), None)
    if scene is None:
        scene = next((item for item in bpy.data.scenes
                      if scene_role(item) == PART_STUDIO and any(obj.get("cad_generated") for obj in item.objects)), None)
        if scene is None:
            scene = bpy.data.scenes.new("CAD — Part Studio")
        scene["cad_scene_role"] = PART_STUDIO
    return scene


def assembly_scene():
    """Return the dedicated Assembly display Scene, creating it when needed."""
    scene = next((item for item in bpy.data.scenes if scene_role(item) == ASSEMBLY), None)
    if scene is None:
        scene = bpy.data.scenes.new("CAD — Assembly")
        scene["cad_scene_role"] = ASSEMBLY
    return scene


def ensure_source_collection(part_id: str):
    """Keep exactly one UUID-owned source Collection, retained even when unlinked."""
    root = next((item for item in bpy.data.collections if item.get("cad_source_root")), None)
    if root is None:
        root = bpy.data.collections.new("CAD_SOURCE_ROOT")
        root["cad_source_root"] = True
    root.use_fake_user = True
    collection = next((item for item in bpy.data.collections
                       if item.get("cad_source_collection") and item.get("cad_part_id") == part_id), None)
    if collection is None:
        collection = bpy.data.collections.new(f"CAD_PART_{part_id}")
        collection["cad_source_collection"] = True
        collection["cad_part_id"] = part_id
    collection.instance_offset = (0.0, 0.0, 0.0)
    if collection.name not in root.children:
        root.children.link(collection)
    return collection


def show_active_part(scene, part_id: str | None) -> None:
    """Link only the selected source into the authoring Scene; no global hiding."""
    if scene_role(scene) != PART_STUDIO:
        return
    for collection in list(scene.collection.children):
        if collection.get("cad_source_collection") and collection.get("cad_part_id") != part_id:
            scene.collection.children.unlink(collection)
    if part_id:
        collection = ensure_source_collection(part_id)
        if collection.name not in scene.collection.children:
            scene.collection.children.link(collection)
    redraw_all()


def _assembly_collection(assembly_id: str):
    collection = next((item for item in bpy.data.collections
                       if item.get("cad_assembly_collection") and item.get("cad_assembly_id") == assembly_id), None)
    if collection is None:
        collection = bpy.data.collections.new(f"CAD_ASSEMBLY_{assembly_id}")
        collection["cad_assembly_collection"] = True
        collection["cad_assembly_id"] = assembly_id
    collection.use_fake_user = True
    return collection


def instance_object(instance_id: str):
    """Resolve a carrier using its UUID, independent of Blender object names."""
    return next((obj for obj in bpy.data.objects if obj.get("cad_instance_id") == instance_id), None)


def sync_assembly(assembly, scene=None) -> None:
    """Reconcile carriers with stored placements, sharing original source Collections."""
    from .adapter import _find_result_object

    collection = _assembly_collection(assembly.id)
    desired = {item.id for item in assembly.instances if not item.suppressed}
    # Allocate every missing carrier before touching existing placements. A
    # failed allocation cannot delete or move an already displayed instance.
    created = []
    try:
        for instance in assembly.instances:
            if instance.suppressed or instance_object(instance.id) is not None:
                continue
            obj = bpy.data.objects.new(instance.name, None)
            created.append(obj)
            obj["cad_instance_id"] = instance.id
            obj["cad_assembly_id"] = assembly.id
            collection.objects.link(obj)
    except Exception:
        for obj in created:
            bpy.data.objects.remove(obj, do_unlink=True)
        raise
    for instance in assembly.instances:
        if instance.suppressed:
            continue
        source = ensure_source_collection(instance.part_studio_id)
        obj = instance_object(instance.id)
        obj.name = instance.name
        obj.instance_type = "COLLECTION"
        obj.instance_collection = source
        obj.empty_display_size = 0.01
        obj["cad_instance_id"] = instance.id
        obj["cad_assembly_id"] = assembly.id
        obj["cad_part_id"] = instance.part_studio_id
        # Quaternion storage avoids Euler float rounding around 180 degrees
        # when Blender reevaluates a carrier after a source mesh update.
        obj.rotation_mode = 'QUATERNION'
        matrix = Matrix(instance.transform)
        if obj.matrix_world != matrix:
            obj.matrix_world = matrix
        obj.lock_location = (True, True, True)
        obj.lock_rotation = (True, True, True)
        obj.lock_scale = (True, True, True)
        result = _find_result_object(instance.part_studio_id)
        stale = bool(source.get("cad_source_stale", False))
        obj["cad_stale"] = stale
        obj["cad_diagnostic"] = (
            "Source Part rebuild failed. Assembly instance is displaying last valid geometry."
            if stale else "Source Part has no result geometry." if result is None else ""
        )
    for obj in list(bpy.data.objects):
        if obj.get("cad_instance_id") and obj.get("cad_assembly_id") == assembly.id and obj.get("cad_instance_id") not in desired:
            bpy.data.objects.remove(obj, do_unlink=True)
    if scene is not None:
        for linked in list(scene.collection.children):
            if linked.get("cad_assembly_collection") and linked != collection:
                scene.collection.children.unlink(linked)
        if collection.name not in scene.collection.children:
            scene.collection.children.link(collection)
    redraw_all()


def commit_assembly(document, assembly, scene=None) -> None:
    """Commit validated placements and roll back document/display on carrier failure."""
    from .adapter import _validate_document, load_document, save_document

    _validate_document(document)
    previous = load_document()
    previous_assembly = previous.get_assembly(assembly.id)
    try:
        sync_assembly(assembly, scene)
        save_document(document)
    except Exception:
        if previous_assembly is None:
            remove_assembly_geometry(assembly.id)
        else:
            sync_assembly(previous_assembly, scene)
        save_document(previous)
        raise


def show_assembly(scene, assembly_id: str) -> None:
    """Display the selected Assembly without touching Part Studio edit state."""
    from .adapter import load_document

    assembly = load_document().get_assembly(assembly_id)
    if assembly is not None:
        sync_assembly(assembly, scene)
    else:
        for collection in list(scene.collection.children):
            if collection.get("cad_assembly_collection"):
                scene.collection.children.unlink(collection)


def remove_assembly_geometry(assembly_id: str) -> None:
    """Delete only owned instance carriers and the Assembly display Collection."""
    for obj in list(bpy.data.objects):
        if obj.get("cad_instance_id") and obj.get("cad_assembly_id") == assembly_id:
            bpy.data.objects.remove(obj, do_unlink=True)
    for collection in list(bpy.data.collections):
        if collection.get("cad_assembly_collection") and collection.get("cad_assembly_id") == assembly_id:
            bpy.data.collections.remove(collection)


def restore_assemblies(document) -> None:
    """Restore every Assembly once, then link each Scene's selected Assembly."""
    if not document.assemblies:
        return
    scene = assembly_scene()
    for assembly in document.assemblies:
        sync_assembly(assembly)
    ui = scene.parametric_cad_ui
    if document.get_assembly(ui.active_assembly_id) is None:
        ui.active_assembly_id = document.assemblies[0].id
    show_assembly(scene, ui.active_assembly_id)


def mark_source_status(part_id: str, stale: bool) -> None:
    """Mark last-valid geometry without changing any Assembly placements."""
    collection = ensure_source_collection(part_id)
    collection["cad_source_stale"] = stale
    for obj in bpy.data.objects:
        if obj.get("cad_instance_id") and obj.get("cad_part_id") == part_id:
            obj["cad_stale"] = stale
            obj["cad_diagnostic"] = (
                "Source Part rebuild failed. Assembly instance is displaying last valid geometry."
                if stale else ""
            )


def sync_instance_selection(scene, obj) -> None:
    """Route Assembly selection without changing the document's active Part."""
    if obj is None or not obj.get("cad_instance_id"):
        return
    ui = scene.parametric_cad_ui
    assembly_id = obj.get("cad_assembly_id")
    if ui.active_assembly_id != assembly_id:
        ui.active_assembly_id = assembly_id
    if ui.selected_instance_id != obj["cad_instance_id"]:
        ui.selected_instance_id = obj["cad_instance_id"]


def redraw_all() -> None:
    """Invalidate every window's viewport after shared source updates."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def open_environment(context, role: str, *, new_window: bool = True):
    """Reuse a main window for a role, or open one using Blender's window operator."""
    scene = assembly_scene() if role == ASSEMBLY else part_studio_scene()
    if bpy.app.background:
        return None
    windows = context.window_manager.windows
    existing = next((window for window in windows if window.scene == scene), None)
    if existing is not None:
        return existing
    window = context.window
    if new_window:
        previous = {item.as_pointer() for item in windows}
        bpy.ops.wm.window_new_main()
        window = next((item for item in windows if item.as_pointer() not in previous), None)
        if window is None:
            raise RuntimeError("Blender did not create a new main window.")
    window.scene = scene
    return window
