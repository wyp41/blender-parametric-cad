"""Viewport picking for transient Blender geometry selections."""

from __future__ import annotations

import json

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector

from ...sketch.plane import PlaneReference
from ...core.serialization import edge_reference_to_dict, plane_reference_to_dict
from ..adapter import load_document_from_scene, rebuild_part, sync_active_part_from_object
from ..viewport.sketch_overlay import (
    clear_face_selection,
    clear_edge_selection,
    set_face_hover,
    set_face_selection,
    set_edge_hover,
    set_edge_selection,
    tag_redraw,
)
from ..viewport.provenance import get_edge_candidates, get_face_candidate


def _window_region(context):
    return next(
        (region for region in context.area.regions if region.type == "WINDOW"),
        None,
    )


def _raycast(context, event):
    region = _window_region(context)
    if region is None:
        return None
    region_3d = context.space_data.region_3d
    coordinate = (event.mouse_x - region.x, event.mouse_y - region.y)
    origin = view3d_utils.region_2d_to_origin_3d(region, region_3d, coordinate)
    direction = view3d_utils.region_2d_to_vector_3d(region, region_3d, coordinate)
    hit, _location, _normal, polygon_index, obj, _matrix = context.scene.ray_cast(
        context.evaluated_depsgraph_get(), origin, direction
    )
    if not hit or obj is None:
        return None
    # Picking a generated object is an explicit Part Studio transition.  This
    # prevents face references from being resolved against whichever studio
    # happened to be active before the click.
    sync_active_part_from_object(context.scene, obj)
    active_part = load_document_from_scene(context.scene).active_part
    if active_part is None or obj.get("cad_part_id") != active_part.id:
        return obj, polygon_index, None
    reference = _face_reference(obj, polygon_index)
    return obj, polygon_index, reference


def _face_reference(obj, polygon_index: int) -> PlaneReference | None:
    if not obj.get("cad_generated"):
        return None
    candidate = get_face_candidate(obj, polygon_index)
    return candidate.semantic_plane if candidate else None


def _face_selection_message(obj, polygon_index: int) -> str:
    candidate = get_face_candidate(obj, polygon_index)
    if candidate is not None and candidate.resolution_error:
        return candidate.resolution_error
    return "This face cannot yet be used as a persistent Sketch reference."


def _edge_raycast(context, event):
    region = _window_region(context)
    if region is None:
        return None
    region_3d = context.space_data.region_3d
    coordinate = (event.mouse_x - region.x, event.mouse_y - region.y)
    origin = view3d_utils.region_2d_to_origin_3d(region, region_3d, coordinate)
    direction = view3d_utils.region_2d_to_vector_3d(region, region_3d, coordinate)
    hit, _location, _normal, _polygon_index, obj, _matrix = context.scene.ray_cast(
        context.evaluated_depsgraph_get(), origin, direction
    )
    if not hit or obj is None:
        return None
    sync_active_part_from_object(context.scene, obj)
    document = load_document_from_scene(context.scene)
    active_part = document.active_part
    if active_part is None or obj.get("cad_part_id") != active_part.id:
        return obj, None, None
    candidates = get_edge_candidates(obj)
    best = None
    best_distance = 12.0 * 12.0
    for edge_index, candidate in candidates.items():
        first = view3d_utils.location_3d_to_region_2d(
            region, region_3d, obj.matrix_world @ Vector(candidate.start)
        )
        second = view3d_utils.location_3d_to_region_2d(
            region, region_3d, obj.matrix_world @ Vector(candidate.end)
        )
        if first is None or second is None:
            continue
        distance = _point_segment_distance_squared(
            coordinate, (float(first.x), float(first.y)), (float(second.x), float(second.y))
        )
        if distance <= best_distance:
            best_distance = distance
            best = (obj, edge_index, candidate)
    return best or (obj, None, None)


def _point_segment_distance_squared(point, first, second) -> float:
    dx = second[0] - first[0]
    dy = second[1] - first[1]
    denominator = dx * dx + dy * dy
    if denominator <= 1e-12:
        return (point[0] - first[0]) ** 2 + (point[1] - first[1]) ** 2
    factor = max(0.0, min(1.0, ((point[0] - first[0]) * dx + (point[1] - first[1]) * dy) / denominator))
    closest = (first[0] + factor * dx, first[1] + factor * dy)
    return (point[0] - closest[0]) ** 2 + (point[1] - closest[1]) ** 2


def _edge_selection_message(hit) -> str:
    if hit is not None and hit[2] is not None and hit[2].resolution_error:
        return hit[2].resolution_error
    return "This edge cannot yet be used as a persistent straight-edge reference."


class PARAMETRIC_CAD_OT_select_face(bpy.types.Operator):
    bl_idname = "parametric_cad.select_face"
    bl_label = "Select Face"
    bl_description = (
        "Select a persistent planar support on Extrude, Boolean, Transform or Mirror results"
    )
    bl_options = {"BLOCKING"}

    def invoke(self, context, _event):
        if context.area.type != "VIEW_3D":
            return {"CANCELLED"}
        part = load_document_from_scene(context.scene).active_part
        if part is None:
            self.report({"ERROR"}, "Create a Part Studio first")
            return {"CANCELLED"}
        # Rebuild on entry also rehydrates the runtime-only provenance registry
        # after a .blend file has been reopened.
        rebuild_part(context.scene, part.id)
        clear_face_selection()
        context.window_manager.modal_handler_add(self)
        context.area.header_text_set(
            "CAD: click a supported planar surface; Esc cancels"
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            set_face_hover(None)
            context.area.header_text_set(None)
            return {"CANCELLED"}
        if event.type == "MOUSEMOVE":
            set_face_hover(_raycast(context, event))
            return {"RUNNING_MODAL"}
        if event.type != "LEFTMOUSE" or event.value != "PRESS":
            return {"RUNNING_MODAL"}

        hit = _raycast(context, event)
        reference = hit[2] if hit is not None else None
        if reference is None:
            self.report(
                {"WARNING"},
                _face_selection_message(hit[0], hit[1]) if hit is not None
                else "This face cannot yet be used as a persistent Sketch reference.",
            )
            set_face_hover(None)
            context.area.header_text_set(None)
            return {"FINISHED"}

        ui = context.scene.parametric_cad_ui
        ui.selected_face_reference = json.dumps(
            plane_reference_to_dict(reference), separators=(",", ":"), sort_keys=True
        )
        set_face_selection(hit)
        set_face_hover(None)
        context.area.header_text_set(None)
        label = reference.role.replace("_", " ").title()
        if reference.source_entity_id:
            label += f" ({reference.source_entity_id[:8]})"
        self.report({"INFO"}, f"Selected {label}")
        tag_redraw()
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_select_edge(bpy.types.Operator):
    bl_idname = "parametric_cad.select_edge"
    bl_label = "Select Edges"
    bl_description = "Select persistent straight edges; Shift-click adds edges"
    bl_options = {"BLOCKING"}

    def invoke(self, context, _event):
        if context.area.type != "VIEW_3D":
            return {"CANCELLED"}
        part = load_document_from_scene(context.scene).active_part
        if part is None:
            self.report({"ERROR"}, "Create a Part Studio first")
            return {"CANCELLED"}
        rebuild_part(context.scene, part.id)
        ui = context.scene.parametric_cad_ui
        ui.selected_edge_references = "[]"
        clear_edge_selection()
        context.window_manager.modal_handler_add(self)
        context.area.header_text_set(
            "CAD: click an edge; Shift-click adds edges; Enter confirms; Esc cancels"
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            set_edge_hover(None)
            context.area.header_text_set(None)
            return {"CANCELLED"}
        if event.type in {"RET", "NUMPAD_ENTER"}:
            ui = context.scene.parametric_cad_ui
            if not ui.selected_edge_references or ui.selected_edge_references == "[]":
                self.report({"WARNING"}, "Select at least one supported straight edge.")
                return {"RUNNING_MODAL"}
            set_edge_hover(None)
            context.area.header_text_set(None)
            return {"FINISHED"}
        if event.type == "MOUSEMOVE":
            set_edge_hover(_edge_raycast(context, event))
            return {"RUNNING_MODAL"}
        if event.type != "LEFTMOUSE" or event.value != "PRESS":
            return {"RUNNING_MODAL"}

        hit = _edge_raycast(context, event)
        candidate = hit[2] if hit is not None else None
        reference = candidate.semantic_reference if candidate is not None else None
        if reference is None:
            self.report({"WARNING"}, _edge_selection_message(hit))
            return {"RUNNING_MODAL"}

        ui = context.scene.parametric_cad_ui
        try:
            selected = json.loads(ui.selected_edge_references or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            selected = []
        references = []
        if event.shift:
            references.extend(selected)
        references.append(edge_reference_to_dict(reference))
        unique = []
        seen = set()
        for item in references:
            key = json.dumps(item, sort_keys=True, separators=(",", ":"))
            if key not in seen:
                seen.add(key)
                unique.append(item)
        ui.selected_edge_references = json.dumps(unique, separators=(",", ":"), sort_keys=True)
        set_edge_selection([hit] if not event.shift else _selected_edge_hits(hit, unique))
        set_edge_hover(None)
        self.report({"INFO"}, f"Selected {len(unique)} persistent edge(s); press Enter to confirm")
        tag_redraw()
        return {"RUNNING_MODAL"}


def _selected_edge_hits(current_hit, references):
    obj = current_hit[0]
    selected = []
    wanted = {
        json.dumps(item, sort_keys=True, separators=(",", ":")) for item in references
    }
    for edge_index, candidate in get_edge_candidates(obj).items():
        reference = candidate.semantic_reference
        if reference is None:
            continue
        data = json.dumps(edge_reference_to_dict(reference), sort_keys=True, separators=(",", ":"))
        if data in wanted:
            selected.append((obj, edge_index, candidate))
    return selected or [current_hit]


CLASSES = (PARAMETRIC_CAD_OT_select_face, PARAMETRIC_CAD_OT_select_edge)
