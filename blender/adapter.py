"""Single Blender persistence and rebuild integration service.

The Blender scene property is only a transport for the persistent CAD JSON.  A
scene can outlive the add-on that created it, so every access goes through the
guarded helpers below instead of assuming that the custom properties are
registered.
"""

from __future__ import annotations

import json
from math import isfinite
from pathlib import Path

import bpy

from ..core.document import CadDocument
from ..core.evaluator import EvaluationResult, PartEvaluator
from ..core.serialization import dumps, loads
from ..geometry.blender_mesh_backend import BlenderMeshBackend
from .viewport.provenance import clear_face_provenance, set_face_provenance


CAD_ADDON_ID = "blender_parametric_cad"
CAD_DOCUMENT_PROPERTY = "parametric_cad_document"
CAD_RUNTIME_ERROR_PROPERTY = "parametric_cad_runtime_error"
CAD_SCHEMA_VERSION = 2


class CadDocumentError(ValueError):
    """User-facing error raised when the CAD scene state is unavailable."""


def addon_enabled() -> bool:
    """Return whether Blender has registered this add-on's scene state.

    Checking the registered Scene property is the reliable signal while the
    extension is running.  Preferences are consulted as a secondary signal so
    a missing registration produces a useful enable/re-enable message.
    """

    try:
        if hasattr(bpy.types.Scene, CAD_DOCUMENT_PROPERTY):
            return True
    except (AttributeError, RuntimeError):
        pass
    try:
        addons = getattr(getattr(bpy.context, "preferences", None), "addons", {})
        return any(
            str(key).split(".")[-1] == CAD_ADDON_ID for key in addons.keys()
        )
    except (AttributeError, RuntimeError):
        return False


def _scene_property_available(scene: bpy.types.Scene) -> bool:
    try:
        return hasattr(scene, CAD_DOCUMENT_PROPERTY)
    except (AttributeError, ReferenceError, RuntimeError):
        return False


def _validate_document(document: CadDocument) -> CadDocument:
    if int(getattr(document, "schema_version", 0)) != CAD_SCHEMA_VERSION:
        raise CadDocumentError(
            "Unsupported CAD schema version: "
            f"{getattr(document, 'schema_version', None)!r}; expected {CAD_SCHEMA_VERSION}."
        )
    part_ids: set[str] = set()
    feature_ids: set[str] = set()
    for part in document.parts:
        if not part.id or part.id in part_ids:
            raise CadDocumentError("CAD document contains duplicate or missing Part Studio IDs.")
        part_ids.add(part.id)
        for feature in part.features:
            if not feature.id or feature.id in feature_ids:
                raise CadDocumentError("CAD document contains duplicate or missing Feature IDs.")
            feature_ids.add(feature.id)
    if document.active_part_id and document.active_part_id not in part_ids:
        raise CadDocumentError(
            f"Active Part Studio {document.active_part_id!r} is not present in the document."
        )
    return document


def load_document_from_scene(scene: bpy.types.Scene) -> CadDocument:
    if scene is None:
        raise CadDocumentError("No Blender scene is available for CAD document loading.")
    if not _scene_property_available(scene):
        if not addon_enabled():
            raise CadDocumentError(
                "Blender Parametric CAD is not enabled. Enable the extension in "
                "Edit > Preferences > Extensions, then reopen this file."
            )
        raise CadDocumentError(
            "Blender Parametric CAD scene properties are not registered. "
            "Disable and re-enable the extension, then reopen this file."
        )
    raw = getattr(scene, CAD_DOCUMENT_PROPERTY, "")
    if raw in (None, ""):
        return CadDocument()
    if not isinstance(raw, str):
        raise CadDocumentError("The CAD document scene property is not valid JSON text.")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CadDocumentError(f"CAD document JSON is invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise CadDocumentError("CAD document JSON must contain an object at its root.")
    try:
        version = int(payload.get("schema_version", 1))
    except (TypeError, ValueError) as exc:
        raise CadDocumentError("CAD document schema_version must be an integer.") from exc
    if version not in {1, CAD_SCHEMA_VERSION}:
        raise CadDocumentError(
            f"Unsupported CAD schema version: {version}; supported versions are 1 and {CAD_SCHEMA_VERSION}."
        )
    try:
        return _validate_document(loads(raw))
    except CadDocumentError:
        raise
    except (TypeError, ValueError, KeyError, IndexError) as exc:
        raise CadDocumentError(f"CAD document schema is invalid: {exc}") from exc


def save_document_to_scene(scene: bpy.types.Scene, document: CadDocument) -> None:
    if scene is None or not _scene_property_available(scene):
        raise CadDocumentError(
            "Blender Parametric CAD is not enabled; cannot save the CAD document."
        )
    scene.parametric_cad_document = dumps(_validate_document(document))


def set_runtime_error(scene: bpy.types.Scene, message: str | None) -> None:
    """Persist a short diagnostic for the panel without corrupting CAD JSON."""

    if scene is None:
        return
    if message:
        value = str(message)
        if scene.get(CAD_RUNTIME_ERROR_PROPERTY) != value:
            scene[CAD_RUNTIME_ERROR_PROPERTY] = value
    elif CAD_RUNTIME_ERROR_PROPERTY in scene:
        del scene[CAD_RUNTIME_ERROR_PROPERTY]


def sync_active_part_from_object(scene: bpy.types.Scene, obj) -> str | None:
    """Make a selected generated object select its owning Part Studio."""

    if obj is None:
        return None
    try:
        part_id = obj.get("cad_part_id")
    except (AttributeError, ReferenceError):
        part_id = None
    if not part_id:
        return None
    document = load_document_from_scene(scene)
    if document.get_part(part_id) is None:
        return None
    changed = document.active_part_id != part_id
    if changed:
        document.set_active_part(part_id)
        save_document_to_scene(scene, document)
    ui = getattr(scene, "parametric_cad_ui", None)
    if ui is not None and ui.active_part_id != part_id:
        # This is an explicit selection transition, never a panel draw side
        # effect.  The property callback is therefore safe to run here.
        ui.active_part_id = part_id
    return part_id


def validate_cad_document(scene: bpy.types.Scene) -> list[str]:
    """Return actionable document/history/mesh validation diagnostics.

    Validation is deliberately read-only: it never changes feature statuses or
    replaces a generated object.  Rebuild remains the operation that updates
    the persistent status fields.
    """

    try:
        document = load_document_from_scene(scene)
    except CadDocumentError as exc:
        return [str(exc)]
    from ..features.extrude import ExtrudeFeature
    from ..features.mirror import MirrorFeature
    from ..features.revolve import RevolveFeature
    from ..features.transform import TransformFeature
    from ..sketch.profile import ProfileDetector
    from ..sketch.sketch import SketchFeature
    from ..sketch.solver import SketchSolver

    diagnostics: list[str] = []
    for part in document.parts:
        feature_ids: set[str] = set()
        for feature in part.features:
            for dependency in feature.dependencies:
                if dependency not in feature_ids:
                    diagnostics.append(
                        f"{part.name}/{feature.name}: dangling dependency {dependency}."
                    )
            feature_ids.add(feature.id)
            if feature.status in {"ERROR", "BLOCKED"} and feature.error_message:
                diagnostics.append(f"{part.name}/{feature.name}: {feature.error_message}")
            if isinstance(feature, SketchFeature):
                solved = SketchSolver().solve(feature)
                if not solved.success:
                    diagnostics.append(f"{part.name}/{feature.name}: {solved.message}")
                reference = feature.plane_reference
                if reference.reference_type != "DATUM" and not reference.feature_id:
                    diagnostics.append(f"{part.name}/{feature.name}: sketch plane reference is missing.")
                try:
                    offset = float(reference.offset)
                except (TypeError, ValueError):
                    offset = None
                if offset is None or not isfinite(offset):
                    diagnostics.append(f"{part.name}/{feature.name}: sketch plane offset is not finite.")
            elif isinstance(feature, (ExtrudeFeature, RevolveFeature)):
                source = part.get_feature(feature.sketch_id)
                if not isinstance(source, SketchFeature):
                    diagnostics.append(
                        f"{part.name}/{feature.name}: source Sketch {feature.sketch_id} is missing."
                    )
                else:
                    profile = ProfileDetector().detect(source)
                    if not profile.success:
                        diagnostics.append(f"{part.name}/{feature.name}: {profile.message}")
            elif isinstance(feature, TransformFeature):
                try:
                    feature.as_transform()
                except (TypeError, ValueError) as exc:
                    diagnostics.append(f"{part.name}/{feature.name}: invalid transform: {exc}")
            elif isinstance(feature, MirrorFeature):
                source = part.get_feature(feature.source_feature_id)
                if not isinstance(source, (ExtrudeFeature, RevolveFeature)) or source.operation != "ADD":
                    diagnostics.append(
                        f"{part.name}/{feature.name}: mirror source must be an additive Extrude or Revolve."
                    )
                source_index = part.get_feature_index(feature.source_feature_id)
                feature_index = part.get_feature_index(feature.id)
                if source_index is None or feature_index is None or source_index >= feature_index:
                    diagnostics.append(
                        f"{part.name}/{feature.name}: mirror source must precede the Mirror feature."
                    )
                reference = feature.mirror_plane
                if reference.reference_type not in {"DATUM", "FEATURE_PLANE", "FACE"}:
                    diagnostics.append(f"{part.name}/{feature.name}: unsupported mirror plane reference.")
                if reference.reference_type == "DATUM" and reference.datum_plane not in {"XY", "XZ", "YZ"}:
                    diagnostics.append(f"{part.name}/{feature.name}: invalid mirror datum plane.")
                if reference.reference_type != "DATUM" and not reference.feature_id:
                    diagnostics.append(f"{part.name}/{feature.name}: mirror plane reference is missing.")
                try:
                    offset = float(reference.offset)
                except (TypeError, ValueError):
                    offset = None
                if offset is None or not isfinite(offset):
                    diagnostics.append(f"{part.name}/{feature.name}: mirror plane offset is not finite.")

        result_object = _find_result_object(part.id)
        if result_object is None:
            continue
        mesh = getattr(result_object, "data", None)
        if mesh is None or len(mesh.vertices) == 0 or len(mesh.polygons) == 0:
            diagnostics.append(f"{part.name}: generated result is empty.")
        elif (components := _mesh_component_count(mesh)) != 1:
            diagnostics.append(
                f"{part.name}: generated result has {components} disconnected components."
            )
    return diagnostics


def _selected_object():
    try:
        active = bpy.context.view_layer.objects.active
        if active is not None:
            return active
        selected = bpy.context.selected_objects
        return selected[0] if selected else None
    except (AttributeError, ReferenceError, RuntimeError):
        return None


@bpy.app.handlers.persistent
def _on_depsgraph_update_post(scene, _depsgraph) -> None:
    obj = _selected_object()
    if obj is None:
        return
    try:
        sync_active_part_from_object(scene, obj)
        if obj.get("cad_generated") and getattr(obj, "mode", "OBJECT") == "EDIT":
            set_runtime_error(
                scene,
                "Generated result meshes are read-only. Use Edit CAD History to "
                "edit the source Sketch or Feature.",
            )
    except CadDocumentError as exc:
        set_runtime_error(scene, str(exc))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        set_runtime_error(scene, f"CAD selection sync failed: {exc}")


@bpy.app.handlers.persistent
def _on_load_post(_dummy) -> None:
    """Validate and rehydrate generated meshes after opening a .blend file."""

    scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return
    try:
        document = load_document_from_scene(scene)
        ui = getattr(scene, "parametric_cad_ui", None)
        if ui is not None:
            desired = document.active_part_id or "NONE"
            if ui.active_part_id != desired:
                # Restore UI state here, outside draw(), so Blender permits the
                # ID-property update and the callback can clear stale edits.
                ui.active_part_id = desired
        failures: list[str] = []
        for part in document.parts:
            result = rebuild_part(scene, part.id)
            if not result.success:
                failures.extend(
                    f"{error.feature_name}: {error.message}" for error in result.errors
                )
        set_runtime_error(
            scene,
            "CAD restore completed with errors: " + "; ".join(failures)
            if failures
            else None,
        )
    except CadDocumentError as exc:
        set_runtime_error(scene, str(exc))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        set_runtime_error(scene, f"CAD restore failed: {exc}")


def register_handlers() -> None:
    handlers = bpy.app.handlers
    if _on_load_post not in handlers.load_post:
        handlers.load_post.append(_on_load_post)
    if _on_depsgraph_update_post not in handlers.depsgraph_update_post:
        handlers.depsgraph_update_post.append(_on_depsgraph_update_post)
    scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        _on_load_post(None)


def unregister_handlers() -> None:
    handlers = bpy.app.handlers
    for collection, callback in (
        (handlers.load_post, _on_load_post),
        (handlers.depsgraph_update_post, _on_depsgraph_update_post),
    ):
        if callback in collection:
            collection.remove(callback)


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

    result_object = _find_result_object(part.id)
    if result_object is not None and getattr(result_object, "mode", "OBJECT") == "EDIT":
        from ..core.evaluator import EvaluationError

        message = (
            "Generated result meshes are read-only. Use Edit CAD History to edit "
            "the source Sketch or Feature."
        )
        set_runtime_error(scene, message)
        return EvaluationResult(
            False,
            errors=[EvaluationError(part.id, part.name, message)],
        )

    result = PartEvaluator(BlenderMeshBackend()).evaluate(part)
    save_document_to_scene(scene, document)
    display = _ensure_collection(scene, "CAD", "DISPLAY")

    # Evaluation is transactional from the viewport's point of view.  The
    # evaluator may expose a partial body for diagnostics, but a failed
    # history never replaces or removes the last valid generated mesh.
    if not result.success:
        set_runtime_error(
            scene,
            "; ".join(
                f"{error.feature_name}: {error.message}" for error in result.errors
            )
            or f"{part.name} rebuild failed.",
        )
        return result
    set_runtime_error(scene, None)

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
    evaluated_features = result.context.evaluated_features if result.context else {}
    evaluated = list(evaluated_features.values())
    if evaluated:
        terminal = evaluated[-1]
        result_object["cad_feature_id"] = terminal.id
        source_sketch_id = getattr(terminal, "sketch_id", "")
        if source_sketch_id:
            result_object["cad_source_sketch_id"] = source_sketch_id
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


def _mesh_component_count(mesh) -> int:
    """Count face-connected components without changing the generated mesh."""

    edge_faces: dict[tuple[int, int], list[int]] = {}
    for face_index, polygon in enumerate(getattr(mesh, "polygons", ())):
        vertices = tuple(polygon.vertices)
        if len(vertices) < 3:
            continue
        for index, vertex_index in enumerate(vertices):
            edge = tuple(sorted((vertex_index, vertices[(index + 1) % len(vertices)])))
            edge_faces.setdefault(edge, []).append(face_index)
    neighbors: dict[int, set[int]] = {}
    for faces in edge_faces.values():
        for face_index in faces:
            neighbors.setdefault(face_index, set()).update(
                neighbor for neighbor in faces if neighbor != face_index
            )
    components = 0
    visited: set[int] = set()
    for start in range(len(getattr(mesh, "polygons", ()))):
        if start in visited:
            continue
        components += 1
        stack = [start]
        visited.add(start)
        while stack:
            face_index = stack.pop()
            for neighbor in neighbors.get(face_index, ()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)
    return components


def _remove_result_object(result_object: bpy.types.Object) -> None:
    mesh = result_object.data
    clear_face_provenance(result_object)
    bpy.data.objects.remove(result_object, do_unlink=True)
    if mesh and mesh.users == 0:
        bpy.data.meshes.remove(mesh)
