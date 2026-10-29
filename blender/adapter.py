"""File-level CAD persistence, legacy migration, and source mesh evaluation."""

from __future__ import annotations

import json
from math import isfinite
from pathlib import Path

import bpy

from ..core.document import CadDocument
from ..core.evaluator import EvaluationResult, PartEvaluator
from ..core.serialization import dumps, loads
from ..geometry.blender_mesh_backend import BlenderMeshBackend
from .viewport.provenance import (
    clear_runtime_caches,
    clear_face_provenance,
    set_edge_candidates,
    set_face_candidates,
    set_face_provenance,
)


CAD_ADDON_ID = "blender_parametric_cad"
CAD_DOCUMENT_PROPERTY = "parametric_cad_document"
CAD_RUNTIME_ERROR_PROPERTY = "parametric_cad_runtime_error"
CAD_SCHEMA_VERSION = 3
CAD_DOCUMENT_TEXT = "CAD_DOCUMENT.json"


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
    from ..core.assembly import validate_instance_transform

    assembly_ids, instance_ids = set(), set()
    for assembly in document.assemblies:
        if not assembly.id or assembly.id in assembly_ids:
            raise CadDocumentError("Duplicate or missing Assembly UUID.")
        assembly_ids.add(assembly.id)
        for instance in assembly.instances:
            if not instance.id or instance.id in instance_ids:
                raise CadDocumentError("Duplicate or missing Instance UUID.")
            instance_ids.add(instance.id)
            if instance.part_studio_id not in part_ids:
                raise CadDocumentError(f"Unknown source Part Studio: {instance.part_studio_id}")
            validate_instance_transform(instance.transform)
    return document


def _parse_document(raw: str) -> CadDocument:
    """Validate JSON before any migration can replace legacy storage."""
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("CAD document JSON must contain an object at its root.")
        return _validate_document(loads(raw))
    except (TypeError, ValueError, KeyError, IndexError) as exc:
        raise CadDocumentError(f"CAD document schema is invalid: {exc}") from exc


def load_document() -> CadDocument:
    """Load the single file-level document, migrating all legacy Scenes atomically."""
    text = bpy.data.texts.get(CAD_DOCUMENT_TEXT)
    if text is not None:
        return _parse_document(text.as_string())
    candidates = []
    for scene in bpy.data.scenes:
        raw = getattr(scene, CAD_DOCUMENT_PROPERTY, "") or scene.get(CAD_DOCUMENT_PROPERTY, "")
        if raw:
            document = _parse_document(raw)
            if document.parts or document.assemblies:
                candidates.append((scene.name, document))
    if candidates:
        signatures = {dumps(document) for _, document in candidates}
        if len(signatures) != 1:
            raise CadDocumentError("MIGRATION_CONFLICT: conflicting legacy CAD documents in Scenes: "
                                   + ", ".join(name for name, _ in candidates))
        document = candidates[0][1]
        save_document(document)
        return document
    return CadDocument()


def save_document(document: CadDocument) -> None:
    """Write one persistent Text datablock and retire writable Scene copies."""
    # Blender inserts Text contents character by character. A megabyte-long
    # JSON line makes that insertion quadratic; short JSON lines keep large
    # generated sketches practical while preserving exactly the same schema.
    raw = json.dumps(_validate_document(document).to_dict(), sort_keys=True, indent=2)
    text = bpy.data.texts.get(CAD_DOCUMENT_TEXT)
    if text is None:
        text = bpy.data.texts.new(CAD_DOCUMENT_TEXT)
    text.use_fake_user = True
    if text.as_string() != raw:
        text.clear()
        text.write(raw)
    for scene in bpy.data.scenes:
        if getattr(scene, CAD_DOCUMENT_PROPERTY, ""):
            setattr(scene, CAD_DOCUMENT_PROPERTY, "")
        if CAD_DOCUMENT_PROPERTY in scene:
            del scene[CAD_DOCUMENT_PROPERTY]


def load_document_from_scene(scene: bpy.types.Scene) -> CadDocument:
    """Compatibility wrapper; Scene selection does not determine document ownership."""
    return load_document()


def save_document_to_scene(scene: bpy.types.Scene, document: CadDocument) -> None:
    """Compatibility wrapper for the canonical file-level store."""
    save_document(document)


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
    """Make a selected generated object select its owning Part Studio/Feature."""

    from .environments import scene_role, sync_instance_selection

    if scene_role(scene) == "ASSEMBLY":
        sync_instance_selection(scene, obj)
        return None
    if obj is None or obj.get("cad_instance_id"):
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
    if ui is not None:
        feature_id = obj.get("cad_feature_id")
        feature = document.get_part(part_id).get_feature(feature_id) if feature_id else None
        if (
            feature is not None
            and ui.mode != "SKETCH_EDIT"
            and ui.active_feature_id != feature.id
        ):
            # Result objects carry the terminal CAD feature UUID.  Reuse the
            # same hydration path as a history-row selection so Revolve,
            # Transform, and Mirror parameters cannot remain stale in the UI.
            from .operators.part import _set_active_feature

            _set_active_feature(ui, feature)
        elif feature is not None:
            ui.feature_name = feature.name
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
    from ..features.chamfer import ChamferFeature
    from ..features.extrude import ExtrudeFeature
    from ..features.fillet import FilletFeature
    from ..features.mirror import MirrorFeature
    from ..features.revolve import RevolveFeature
    from ..features.transform import TransformFeature
    from ..sketch.entities import SketchLine
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
                    detector = ProfileDetector()
                    if isinstance(feature, RevolveFeature):
                        entities = [
                            entity for entity in source.entities if not entity.construction
                        ]
                        profile = detector.detect_entities(
                            entities, source.deleted_regions
                        )
                        reference = feature.axis_reference
                        if reference.reference_type == "DATUM_AXIS" and reference.axis not in {
                            "X",
                            "Y",
                            "Z",
                        }:
                            diagnostics.append(
                                f"{part.name}/{feature.name}: invalid Revolve datum axis."
                            )
                        elif reference.reference_type == "SKETCH_LINE":
                            axis_sketch = part.get_feature(reference.sketch_id)
                            axis_line = (
                                next(
                                    (
                                        entity
                                        for entity in axis_sketch.entities
                                        if isinstance(entity, SketchLine)
                                        and entity.id == reference.entity_id
                                    ),
                                    None,
                                )
                                if isinstance(axis_sketch, SketchFeature)
                                else None
                            )
                            if axis_line is None:
                                diagnostics.append(
                                    f"{part.name}/{feature.name}: referenced Revolve SketchLine is missing."
                                )
                            if not profile.success and reference.sketch_id == source.id:
                                profile = detector.detect_entities(
                                    [
                                        entity
                                        for entity in entities
                                        if entity.id != reference.entity_id
                                    ],
                                    source.deleted_regions,
                                )
                        elif reference.reference_type != "DATUM_AXIS":
                            diagnostics.append(
                                f"{part.name}/{feature.name}: unsupported Revolve axis reference."
                            )
                    else:
                        profile = detector.detect(source)
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
                if reference.reference_type not in {"DATUM", "FEATURE_PLANE", "FACE", "DERIVED_PLANE"}:
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
            elif isinstance(feature, (ChamferFeature, FilletFeature)):
                amount = feature.distance if isinstance(feature, ChamferFeature) else feature.radius
                label = "chamfer distance" if isinstance(feature, ChamferFeature) else "fillet radius"
                if not isfinite(float(amount)) or float(amount) <= 0.0:
                    diagnostics.append(f"{part.name}/{feature.name}: {label} must be positive and finite.")
                if not feature.edge_references:
                    diagnostics.append(f"{part.name}/{feature.name}: no persistent edges are selected.")
                for reference in feature.edge_references:
                    if getattr(reference, "reference_type", None) != "EDGE":
                        diagnostics.append(
                            f"{part.name}/{feature.name}: invalid persistent edge reference."
                        )

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


@bpy.app.handlers.persistent
def _on_depsgraph_update_post(scene, _depsgraph) -> None:
    # Handlers run for multiple Scenes; use that Scene's ViewLayer, never the
    # globally active window's selection.
    layer = scene.view_layers[0] if scene.view_layers else None
    obj = layer.objects.active if layer else None
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

    _reactivate_mcp_service()
    scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return
    try:
        clear_runtime_caches()
        try:
            from .viewport.sketch_overlay import (
                clear_edge_selection,
                clear_face_selection,
                clear_sketch_selection,
            )

            clear_edge_selection()
            clear_face_selection()
            clear_sketch_selection()
        except (ImportError, ReferenceError, RuntimeError, TypeError):
            pass
        from .environments import part_studio_scene, restore_assemblies, show_active_part

        document = load_document()
        if bpy.data.texts.get(CAD_DOCUMENT_TEXT) is None:
            save_document(document)
        legacy_context = not scene.get("cad_scene_role")
        scene = part_studio_scene()
        if legacy_context and getattr(bpy.context, "window", None) is not None:
            bpy.context.window.scene = scene
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
        show_active_part(scene, document.active_part_id)
        restore_assemblies(load_document())
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
    _remove_stale_handler(handlers.load_post, _on_load_post)
    _remove_stale_handler(handlers.depsgraph_update_post, _on_depsgraph_update_post)
    handlers.load_post.append(_on_load_post)
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
        _remove_stale_handler(collection, callback)


def _remove_stale_handler(collection, callback) -> None:
    """Remove this add-on's previous module instance after a code reload."""

    for registered in list(collection):
        if registered is callback or (
            getattr(registered, "__module__", None) == callback.__module__
            and getattr(registered, "__name__", None) == callback.__name__
        ):
            collection.remove(registered)


def _reactivate_mcp_service() -> None:
    """Re-arm the in-process MCP timer after Blender opens a .blend file."""

    try:
        from ..mcp.blender_worker import _EMBEDDED_SERVICE

        service = _EMBEDDED_SERVICE
        if service is None or service._closed:
            return
        timers = bpy.app.timers
        is_registered = getattr(timers, "is_registered", None)
        if is_registered is None or not is_registered(service.poll):
            timers.register(service.poll, first_interval=0.0)
    except (AttributeError, ImportError, ReferenceError, RuntimeError, TypeError, ValueError):
        # Loading a file must not fail just because the optional MCP service
        # is absent or Blender is still replacing the current scene.
        pass


def remove_part_geometry(part_id: str) -> None:
    """Remove disposable Blender objects owned by one Part Studio."""

    document = load_document()
    if any(item.part_studio_id == part_id for assembly in document.assemblies for item in assembly.instances):
        from ..core.assembly import PartInUseError
        raise PartInUseError(part_id, [
            {"assembly_id": assembly.id, "instance_id": item.id}
            for assembly in document.assemblies for item in assembly.instances
            if item.part_studio_id == part_id
        ])
    for item in list(bpy.data.objects):
        if item.get("cad_generated") and item.get("cad_part_id") == part_id:
            _remove_result_object(item)
    for collection in list(bpy.data.collections):
        if collection.get("cad_source_collection") and collection.get("cad_part_id") == part_id:
            bpy.data.collections.remove(collection)


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
    from ..sketch.plane import register_runtime_evaluation

    register_runtime_evaluation(part.id, result.context)
    save_document_to_scene(scene, document)
    from .environments import ensure_source_collection, mark_source_status, redraw_all, show_active_part

    display = ensure_source_collection(part.id)
    if result_object is not None:
        # Move legacy DISPLAY geometry without changing Object identity.
        if result_object.name not in display.objects:
            display.objects.link(result_object)
        for collection in list(result_object.users_collection):
            if collection != display:
                collection.objects.unlink(result_object)
    mark_source_status(part.id, not result.success)
    from .environments import part_studio_scene
    show_active_part(part_studio_scene(), document.active_part_id)
    redraw_all()

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
        if old_mesh:
            result.body.materials.clear()
            for material in old_mesh.materials:
                result.body.materials.append(material)
        result_object.data = result.body
        result_object.name = f"{part.name}_Result"
        if old_mesh and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)

    from mathutils import Matrix

    result_object.matrix_world = Matrix.Identity(4)
    result_object.lock_location = (True, True, True)
    result_object.lock_rotation = (True, True, True)
    result_object.lock_scale = (True, True, True)
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
    if result.context:
        set_face_candidates(result_object, result.context)
        set_edge_candidates(result_object, result.context)
    result_object.update_tag()
    bpy.context.view_layer.update()
    redraw_all()
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

    from .environments import ensure_source_collection, part_studio_scene

    scene = part_studio_scene()
    source = ensure_source_collection(part_id)
    temporary_link = source.name not in scene.collection.children
    if temporary_link:
        scene.collection.children.link(source)
    layer = scene.view_layers[0]
    try:
        with bpy.context.temp_override(scene=scene, view_layer=layer):
            layer.update()
            selected_objects = [item for item in layer.objects if item.select_get(view_layer=layer)]
            for item in selected_objects:
                item.select_set(False, view_layer=layer)
            result_object.select_set(True, view_layer=layer)
            try:
                operators = {
                    "STL": bpy.ops.wm.stl_export,
                    "OBJ": bpy.ops.wm.obj_export,
                    "PLY": bpy.ops.wm.ply_export,
                }
                # CAD geometry is stored in meters; slicers interpret STL
                # coordinates as millimeters because STL carries no units.
                options = {"global_scale": 1000.0, "use_scene_unit": False} if format_name == "STL" else {}
                status = operators[format_name](filepath=str(path), export_selected_objects=True, **options)
                if "FINISHED" not in status:
                    raise RuntimeError(f"Blender {format_name} export did not finish.")
            finally:
                result_object.select_set(False, view_layer=layer)
                for item in selected_objects:
                    item.select_set(True, view_layer=layer)
    finally:
        if temporary_link:
            scene.collection.children.unlink(source)
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
