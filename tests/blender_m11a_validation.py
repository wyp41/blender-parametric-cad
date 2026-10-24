"""Real Blender 5.1.2 acceptance checks using public MCP operations.

Run with --background --factory-startup --python; outputs go to /tmp by default.
GUI window behavior is covered separately by blender_m11a_gui_validation.py.
"""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys
import tempfile

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import blender_parametric_cad as addon
from blender_parametric_cad.blender import adapter
from blender_parametric_cad.blender.environments import (
    assembly_scene, ensure_source_collection, instance_object, part_studio_scene, sync_assembly,
)
from blender_parametric_cad.mcp.blender_worker import BlenderCadWorker
from blender_parametric_cad.mcp.server import BridgeError, StdioMcpServer


class PublicBridge:
    def __init__(self, worker):
        self.worker = worker

    def call(self, name, arguments):
        try:
            return self.worker.handle(name, arguments)
        except Exception as exc:
            raise BridgeError(str(exc), code=getattr(exc, 'code', 'CAD_ERROR'),
                              details=getattr(exc, 'details', None)) from exc


def public_call(server, tool_name, **arguments):
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": tool_name, "arguments": arguments}})
    assert "error" not in response, response
    result = response["result"]
    assert not result["isError"], result
    return result["structuredContent"]


def mesh_signature(part_id):
    mesh = adapter._find_result_object(part_id).data
    return tuple(tuple(round(value, 7) for value in vertex.co) for vertex in mesh.vertices)


def evaluated_instances(scene):
    """Inspect actual depsgraph instances, including world-space geometry bounds."""
    with bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0]):
        depsgraph = bpy.context.evaluated_depsgraph_get()
        depsgraph.update()
        result = {}
        for item in depsgraph.object_instances:
            if not item.is_instance or item.parent is None:
                continue
            instance_id = item.parent.original.get("cad_instance_id")
            if not instance_id or item.object.type != 'MESH':
                continue
            coordinates = [item.matrix_world @ vertex.co for vertex in item.object.data.vertices]
            result[instance_id] = {
                "width": max(point.x for point in coordinates) - min(point.x for point in coordinates),
                "min_x": min(point.x for point in coordinates),
                "max_x": max(point.x for point in coordinates),
            }
        return result


def create_block(server, name, width, height, depth):
    call = lambda tool_name, **arguments: public_call(server, tool_name, **arguments)
    part_id = call("cad_create_part", name=name)["part"]["id"]
    sketch_id = call("cad_create_sketch", part_id=part_id, plane="XY")["sketch"]["id"]
    rectangle = call("cad_sketch_add_rectangle", sketch_id=sketch_id, width_mm=width, height_mm=height)
    extrude = call("cad_create_extrude", sketch_id=sketch_id, operation="NEW", distance_mm=depth)
    assert extrude["rebuild"]["success"], extrude
    return part_id, sketch_id, rectangle, extrude["feature_id"]


def main():
    addon.register()
    assert bpy.data.texts.get(adapter.CAD_DOCUMENT_TEXT) is not None
    worker = BlenderCadWorker()
    server = StdioMcpServer(PublicBridge(worker))
    call = lambda tool_name, **arguments: public_call(server, tool_name, **arguments)
    a, _, _, _ = create_block(server, "Part A", 80, 50, 20)
    b, sketch_b, rectangle_b, extrude_b = create_block(server, "Part B", 20, 10, 30)
    assembly_id = call("cad_create_assembly", name="Assembly 1")["assembly"]["id"]
    ia = call("cad_add_assembly_instance", assembly_id=assembly_id, part_id=a, name="A")["instance_id"]
    b1 = call("cad_add_assembly_instance", assembly_id=assembly_id, part_id=b, name="B1")["instance_id"]
    b2 = call("cad_add_assembly_instance", assembly_id=assembly_id, part_studio_id=b, name="B2",
              translation_mm=[0, 0, 0], rotation_deg=[0, 0, 0])["instance_id"]
    call("cad_update_assembly_instance", assembly_id=assembly_id, instance_id=b1, translation_mm={"x": -50})
    call("cad_update_assembly_instance", assembly_id=assembly_id, instance_id=b2, translation_mm={"x": 50}, rotation_deg={"z": 180})
    ps, scene = part_studio_scene(), assembly_scene()
    bpy.context.window.scene = scene
    assert worker.scene == ps
    source = ensure_source_collection(b)
    assert instance_object(b1).instance_collection == source == instance_object(b2).instance_collection
    assert tuple(source.instance_offset) == (0, 0, 0)
    result_b = adapter._find_result_object(b)
    source_pointer = source.as_pointer()
    object_pointer = result_b.as_pointer()
    assert result_b.matrix_world.is_identity
    transforms = {identifier: [list(row) for row in instance_object(identifier).matrix_world] for identifier in (b1, b2)}
    carriers = {identifier: instance_object(identifier).as_pointer() for identifier in (ia, b1, b2)}
    before = evaluated_instances(scene)
    assert set(before) == {ia, b1, b2}, before
    assert abs(before[b1]["width"] - .020) < 1e-6, before
    assert abs(before[b1]["min_x"] + .050) < 1e-6, before
    assert abs(before[b2]["max_x"] - .050) < 1e-6, before
    assert not any(obj.get("cad_generated") for obj in scene.objects)
    a_before, b_before = mesh_signature(a), mesh_signature(b)
    # Public source edit while the Assembly Scene is the active context.
    call("cad_sketch_update_rectangle", sketch_id=sketch_b, rectangle_id=rectangle_b["rectangle_id"], width_mm=35)
    after = evaluated_instances(scene)
    assert mesh_signature(b) != b_before
    assert mesh_signature(a) == a_before
    assert all(abs(after[identifier]["width"] - .035) < 1e-6 for identifier in (b1, b2)), after
    assert source.as_pointer() == source_pointer
    assert adapter._find_result_object(b).as_pointer() == object_pointer
    assert transforms == {identifier: [list(row) for row in instance_object(identifier).matrix_world] for identifier in (b1, b2)}, (transforms, {identifier: [list(row) for row in instance_object(identifier).matrix_world] for identifier in (b1, b2)})
    assert carriers == {identifier: instance_object(identifier).as_pointer() for identifier in carriers}
    inspection = call("cad_get_assembly", assembly_id=assembly_id)["assembly"]
    assert {item["id"] for item in inspection["instances"]} == {ia, b1, b2}
    # Selecting carriers must not change the source authoring state.
    ui = ps.parametric_cad_ui
    ui.active_feature_id, ui.active_sketch_id, ui.mode = extrude_b, sketch_b, 'SKETCH_EDIT'
    state = (ui.active_part_id, ui.active_feature_id, ui.active_sketch_id, ui.mode)
    adapter.sync_active_part_from_object(scene, instance_object(b1))
    assert scene.parametric_cad_ui.selected_instance_id == b1
    assert state == (ui.active_part_id, ui.active_feature_id, ui.active_sketch_id, ui.mode)
    # Failed source evaluation keeps the last valid shared mesh and placements.
    document = adapter.load_document()
    document.get_part(b).get_feature(extrude_b).distance = 0
    adapter.save_document(document)
    old_mesh = adapter._find_result_object(b).data.as_pointer()
    failed = adapter.rebuild_part(ps, b)
    assert not failed.success
    assert adapter._find_result_object(b).data.as_pointer() == old_mesh
    assert instance_object(b1)["cad_stale"] and instance_object(b2)["cad_stale"]
    assert "last valid" in instance_object(b1)["cad_diagnostic"]
    assert transforms == {identifier: [list(row) for row in instance_object(identifier).matrix_world] for identifier in (b1, b2)}, (transforms, {identifier: [list(row) for row in instance_object(identifier).matrix_world] for identifier in (b1, b2)})
    document = adapter.load_document()
    document.get_part(b).get_feature(extrude_b).distance = .03
    adapter.save_document(document)
    assert adapter.rebuild_part(ps, b).success
    assert not instance_object(b1)["cad_stale"]
    for _ in range(3):
        assert adapter.rebuild_part(ps, b).success
        sync_assembly(adapter.load_document().get_assembly(assembly_id), scene)
    assert sum(bool(obj.get("cad_generated")) for obj in bpy.data.objects) == 2
    assert sum(bool(obj.get("cad_instance_id")) for obj in bpy.data.objects) == 3
    assert sum(bool(item.get("cad_source_collection")) for item in bpy.data.collections) == 2
    deletion = server.handle({"id": 1, "method": "tools/call", "params": {
        "name": "cad_delete_part", "arguments": {"part_id": b}}})["result"]
    assert deletion["isError"] and deletion["structuredContent"]["error_code"] == "PART_IN_USE", deletion
    # Invalid inputs and a real carrier-allocation failure leave Assembly JSON,
    # existing carrier identity, placement, and source history untouched.
    original_document = adapter.load_document().to_dict()
    for arguments in (
        {"assembly_id": "missing", "part_id": b},
        {"assembly_id": assembly_id, "part_studio_id": "missing"},
        {"assembly_id": assembly_id, "part_id": b, "translation_mm": [float('nan'), 0, 0]},
    ):
        response = server.handle({"id": 1, "method": "tools/call", "params": {
            "name": "cad_add_assembly_instance", "arguments": arguments}})["result"]
        assert response["isError"], response
        assert adapter.load_document().to_dict() == original_document
    from blender_parametric_cad.blender import environments
    objects = bpy.data.objects

    class FailingObjects:
        def __iter__(self):
            return iter(objects)

        def new(self, *args):
            raise RuntimeError("Injected carrier allocation failure")

        def remove(self, *args, **kwargs):
            return objects.remove(*args, **kwargs)

    simulated = SimpleNamespace(data=SimpleNamespace(objects=FailingObjects(), collections=bpy.data.collections, scenes=bpy.data.scenes),
                                context=bpy.context)
    with patch.object(environments, 'bpy', simulated):
        response = server.handle({"id": 1, "method": "tools/call", "params": {
            "name": "cad_add_assembly_instance", "arguments": {"assembly_id": assembly_id, "part_id": b}}})["result"]
    assert response["isError"] and "allocation failure" in str(response), response
    assert adapter.load_document().to_dict() == original_document
    assert carriers == {identifier: instance_object(identifier).as_pointer() for identifier in carriers}
    assert transforms == {identifier: [list(row) for row in instance_object(identifier).matrix_world] for identifier in (b1, b2)}, (transforms, {identifier: [list(row) for row in instance_object(identifier).matrix_world] for identifier in (b1, b2)})
    # Explicit export works from the Assembly context, including an inactive source.
    export_path = str(Path(tempfile.gettempdir()) / "cad_m11a_part_a.stl")
    call("cad_export_part", part_id=a, filepath=export_path, file_format="STL")
    assert Path(export_path).stat().st_size > 84
    saved = adapter.load_document().to_dict()
    path = Path(tempfile.gettempdir()) / "cad_m11a_validation.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    bpy.ops.wm.open_mainfile(filepath=str(path))
    assert adapter.load_document().to_dict() == saved
    assert len([text for text in bpy.data.texts if text.name == adapter.CAD_DOCUMENT_TEXT]) == 1
    assert all(not getattr(item, adapter.CAD_DOCUMENT_PROPERTY, "") for item in bpy.data.scenes)
    scene = assembly_scene()
    assert len(evaluated_instances(scene)) == 3
    call("cad_sketch_update_rectangle", sketch_id=sketch_b, rectangle_id=rectangle_b["rectangle_id"], width_mm=40)
    reopened = evaluated_instances(scene)
    assert all(abs(reopened[identifier]["width"] - .040) < 1e-6 for identifier in (b1, b2)), reopened
    assert transforms == {identifier: [list(row) for row in instance_object(identifier).matrix_world] for identifier in (b1, b2)}, (transforms, {identifier: [list(row) for row in instance_object(identifier).matrix_world] for identifier in (b1, b2)})
    # Suppression removes only the carrier and restores the same persistent UUID.
    call("cad_update_assembly_instance", assembly_id=assembly_id, instance_id=b1, suppressed=True)
    assert instance_object(b1) is None and adapter._find_result_object(b) is not None
    call("cad_update_assembly_instance", assembly_id=assembly_id, instance_id=b1, suppressed=False)
    assert instance_object(b1) is not None
    call("cad_remove_assembly_instance", assembly_id=assembly_id, instance_id=b1)
    assert instance_object(b1) is None and instance_object(b2) is not None
    call("cad_delete_assembly", assembly_id=assembly_id)
    assert adapter._find_result_object(a) and adapter._find_result_object(b)
    assert not any(obj.get("cad_instance_id") for obj in bpy.data.objects)
    call("cad_delete_part", part_id=b)
    assert adapter._find_result_object(b) is None
    assert not any(item.get("cad_source_collection") and item.get("cad_part_id") == b for item in bpy.data.collections)
    # Migrate a copy of an actual existing v2 validation document, never the original.
    original = Path(__file__).parents[2] / "zipstring_cad_mcp_3part.blend"
    if not original.exists():
        # A clean checkout has no external user validation file. Create a v2
        # Scene-storage fixture so this test remains independently runnable.
        legacy_data = adapter.load_document().to_dict()
        legacy_data.pop("assemblies")
        legacy_data["schema_version"] = 2
        bpy.data.texts.remove(bpy.data.texts[adapter.CAD_DOCUMENT_TEXT])
        part_studio_scene().parametric_cad_document = json.dumps(legacy_data)
        original = Path(tempfile.gettempdir()) / "cad_m11a_generated_v2.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(original))
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    bpy.ops.wm.open_mainfile(filepath=str(original))
    migrated = adapter.load_document()
    assert migrated.schema_version == 3 and migrated.parts and not migrated.assemblies
    assert bpy.data.texts.get(adapter.CAD_DOCUMENT_TEXT) is not None
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(tempfile.gettempdir()) / "cad_m11a_legacy_migrated.blend"))
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
    # Conflicting nonempty legacy Scenes fail without changing either payload.
    bpy.data.texts.remove(bpy.data.texts[adapter.CAD_DOCUMENT_TEXT])
    legacy = migrated.to_dict()
    legacy.pop("assemblies")
    legacy["schema_version"] = 2
    first = bpy.data.scenes[0]
    second = bpy.data.scenes.new("Conflicting Legacy")
    first.parametric_cad_document = json.dumps(legacy)
    legacy["parts"][0]["name"] += " conflict"
    second.parametric_cad_document = json.dumps(legacy)
    try:
        adapter.load_document()
    except adapter.CadDocumentError as exc:
        assert "MIGRATION_CONFLICT" in str(exc)
    else:
        raise AssertionError("Conflicting legacy documents were silently accepted")
    assert bpy.data.texts.get(adapter.CAD_DOCUMENT_TEXT) is None
    assert first.parametric_cad_document and second.parametric_cad_document
    # Empty active Scenes cannot erase a nonempty legacy model.
    second.parametric_cad_document = ""
    empty = bpy.data.scenes.new("Empty Active")
    bpy.context.window.scene = empty
    restored = adapter.load_document_from_scene(empty)
    assert restored.parts and restored.parts[0].id == migrated.parts[0].id
    assert all(not item.parametric_cad_document for item in bpy.data.scenes)
    print("M11A_INTEGRATION_PASS: shared geometry, live update, stale state, MCP routing, export, save/reopen, legacy migration, conflict, cleanup")


if __name__ == "__main__":
    main()
