"""Blender-side JSON worker used by :mod:`mcp.server`.

This file is launched once by the stdio MCP bridge with Blender 5.1.2 in
background mode.  All calls run on Blender's main thread, so the existing
``bpy`` adapter and mesh backend remain the source of truth.  The worker never
prints to stdout except for protocol messages; Blender's process output is
discarded by the parent bridge.
"""

from __future__ import annotations

import argparse
import json
from math import pi, radians
from pathlib import Path
import socket
import sys
from typing import Any


def _package_parent() -> Path:
    package_root = Path(__file__).resolve().parent.parent
    parent = package_root.parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))
    return package_root


PACKAGE_ROOT = _package_parent()


class WorkerError(RuntimeError):
    """A user-correctable CAD worker error."""


class BlenderCadWorker:
    """Dispatch high-level CAD tools inside one persistent Blender process."""

    def __init__(self, blend_file: str | None = None, autosave: str | None = None):
        self._bpy = self._load_blender_runtime()
        self._registered_properties = self._ensure_scene_properties()
        self.autosave_path = autosave or blend_file
        if blend_file:
            path = Path(blend_file).expanduser()
            if path.exists():
                status = self._bpy.ops.wm.open_mainfile(filepath=str(path))
                if "FINISHED" not in status:
                    raise WorkerError(f"Could not open Blender file: {path}")

    @staticmethod
    def _load_blender_runtime():
        try:
            import bpy
        except ImportError as exc:  # pragma: no cover - only Blender supplies bpy.
            raise WorkerError("The MCP worker must be launched by Blender 5.1.2.") from exc
        return bpy

    def _ensure_scene_properties(self) -> bool:
        from blender_parametric_cad.blender import properties

        if hasattr(self._bpy.types.Scene, "parametric_cad_document"):
            return False
        properties.register()
        return True

    @property
    def scene(self):
        scene = self._bpy.context.scene
        if scene is None:
            raise WorkerError("The Blender worker has no active scene.")
        return scene

    def handle(self, name: str, arguments: dict[str, Any]) -> Any:
        handlers = {
            "cad_status": self._status,
            "cad_create_part": self._create_part,
            "cad_set_active_part": self._set_active_part,
            "cad_delete_part": self._delete_part,
            "cad_create_sketch": self._create_sketch,
            "cad_add_geometry": self._add_geometry,
            "cad_update_geometry": self._update_geometry,
            "cad_delete_geometry": self._delete_geometry,
            "cad_profile": self._profile,
            "cad_delete_region": self._delete_region,
            "cad_restore_region": self._restore_region,
            "cad_create_extrude": self._create_extrude,
            "cad_create_revolve": self._create_revolve,
            "cad_update_feature": self._update_feature,
            "cad_delete_feature": self._delete_feature,
            "cad_suppress_feature": self._suppress_feature,
            "cad_rollback": self._rollback,
            "cad_rebuild": self._rebuild,
            "cad_export_part": self._export_part,
            "cad_save_scene": self._save_scene,
        }
        if name not in handlers:
            raise WorkerError(f"Unknown CAD tool: {name}")
        if not isinstance(arguments, dict):
            raise WorkerError("Tool arguments must be an object.")
        return handlers[name](arguments)

    def _document(self):
        from blender_parametric_cad.blender.adapter import load_document_from_scene

        return load_document_from_scene(self.scene)

    def _save_document(self, document) -> None:
        from blender_parametric_cad.blender.adapter import save_document_to_scene

        save_document_to_scene(self.scene, document)
        self._autosave()

    def _autosave(self) -> None:
        if not self.autosave_path:
            return
        path = Path(self.autosave_path).expanduser()
        status = self._bpy.ops.wm.save_as_mainfile(filepath=str(path))
        if "FINISHED" not in status:
            raise WorkerError(f"Could not save Blender file: {path}")

    def _part(self, document, arguments: dict[str, Any]):
        part_id = arguments.get("part_id") or document.active_part_id
        part = document.get_part(part_id) if part_id else None
        if part is None:
            raise WorkerError("Part Studio not found. Create one with cad_create_part.")
        return part

    @staticmethod
    def _feature_location(document, feature_id: str):
        if not feature_id:
            raise WorkerError("A feature_id is required.")
        for part in document.parts:
            feature = part.get_feature(feature_id)
            if feature is not None:
                return part, feature
        raise WorkerError(f"Feature not found: {feature_id}")

    @staticmethod
    def _sketch_location(document, sketch_id: str):
        from blender_parametric_cad.sketch.sketch import SketchFeature

        part, feature = BlenderCadWorker._feature_location(document, sketch_id)
        if not isinstance(feature, SketchFeature):
            raise WorkerError(f"Feature is not a Sketch: {sketch_id}")
        return part, feature

    def _status(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        from blender_parametric_cad.core.serialization import document_to_dict

        document = self._document()
        objects = []
        for obj in self._bpy.data.objects:
            if not obj.get("cad_generated"):
                continue
            mesh = getattr(obj, "data", None)
            objects.append(
                {
                    "name": obj.name,
                    "part_id": obj.get("cad_part_id"),
                    "vertices": len(mesh.vertices) if mesh is not None else 0,
                    "polygons": len(mesh.polygons) if mesh is not None else 0,
                }
            )
        return {
            "document": document_to_dict(document),
            "active_part_id": document.active_part_id,
            "generated_objects": objects,
            "blend_file": self._bpy.data.filepath or None,
            "autosave": self.autosave_path,
        }

    def _create_part(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from blender_parametric_cad.core.part import Part
        from blender_parametric_cad.core.serialization import document_to_dict

        document = self._document()
        name = str(arguments.get("name") or "").strip()
        if not name:
            number = len(document.parts) + 1
            existing = {part.name for part in document.parts}
            while f"Part Studio {number}" in existing:
                number += 1
            name = f"Part Studio {number}"
        part = Part(name=name)
        document.add_part(part)
        self._save_document(document)
        return {"part": {"id": part.id, "name": part.name}, "document": document_to_dict(document)}

    def _set_active_part(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from blender_parametric_cad.core.serialization import document_to_dict

        document = self._document()
        part_id = str(arguments.get("part_id") or "")
        document.set_active_part(part_id)
        self._save_document(document)
        return {"active_part_id": document.active_part_id, "document": document_to_dict(document)}

    def _delete_part(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from blender_parametric_cad.blender.adapter import remove_part_geometry
        from blender_parametric_cad.core.serialization import document_to_dict

        document = self._document()
        part_id = str(arguments.get("part_id") or "")
        removed = document.remove_part(part_id)
        if removed is None:
            raise WorkerError(f"Part Studio not found: {part_id}")
        remove_part_geometry(part_id)
        self._save_document(document)
        return {"deleted_part_id": part_id, "document": document_to_dict(document)}

    def _create_sketch(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from blender_parametric_cad.core.references import TopoReference
        from blender_parametric_cad.core.serialization import feature_to_dict
        from blender_parametric_cad.sketch.sketch import SketchFeature

        document = self._document()
        part = self._part(document, arguments)
        name = str(arguments.get("name") or "").strip()
        if not name:
            name = part.next_feature_name("Sketch")
        face_data = arguments.get("face_reference")
        feature_id = arguments.get("feature_id")
        if face_data is not None:
            if not isinstance(face_data, dict):
                raise WorkerError("face_reference must be an object.")
            try:
                sketch = SketchFeature.on_face(name, TopoReference.from_dict(face_data))
            except (TypeError, ValueError, KeyError) as exc:
                raise WorkerError(f"Invalid face_reference: {exc}") from exc
        elif feature_id:
            role = str(arguments.get("role") or "END_PLANE")
            sketch = SketchFeature.on_feature_plane(name, str(feature_id), role)
        else:
            plane = str(arguments.get("plane") or "XY").upper()
            try:
                sketch = SketchFeature.on_plane(name, plane)
            except ValueError as exc:
                raise WorkerError(str(exc)) from exc
        part.add_feature(sketch)
        document.active_part_id = part.id
        self._save_document(document)
        return {"part_id": part.id, "sketch": feature_to_dict(sketch)}

    @staticmethod
    def _mm(arguments: dict[str, Any], key: str) -> float:
        if key not in arguments:
            raise WorkerError(f"Missing geometry field: {key}")
        try:
            return float(arguments[key]) / 1000.0
        except (TypeError, ValueError) as exc:
            raise WorkerError(f"Geometry field {key} must be numeric.") from exc

    @staticmethod
    def _number(arguments: dict[str, Any], key: str) -> float:
        if key not in arguments:
            raise WorkerError(f"Missing numeric field: {key}")
        try:
            return float(arguments[key])
        except (TypeError, ValueError) as exc:
            raise WorkerError(f"Field {key} must be numeric.") from exc

    def _add_geometry(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from blender_parametric_cad.core.serialization import entity_to_dict
        from blender_parametric_cad.sketch.entities import SketchArc, SketchCircle, SketchLine

        document = self._document()
        _part, sketch = self._sketch_location(document, str(arguments.get("sketch_id") or ""))
        geometry = arguments.get("geometry")
        if not isinstance(geometry, dict):
            raise WorkerError("geometry must be an object.")
        kind = str(geometry.get("type") or "").upper()
        construction = bool(geometry.get("construction", False))
        created = []
        if kind == "LINE":
            created.append(
                SketchLine(
                    x1=self._mm(geometry, "x1_mm"),
                    y1=self._mm(geometry, "y1_mm"),
                    x2=self._mm(geometry, "x2_mm"),
                    y2=self._mm(geometry, "y2_mm"),
                    construction=construction,
                )
            )
        elif kind == "CIRCLE":
            diameter = self._mm(geometry, "diameter_mm") if "diameter_mm" in geometry else self._mm(geometry, "radius_mm") * 2.0
            if diameter <= 0.0:
                raise WorkerError("Circle diameter must be greater than zero.")
            created.append(
                SketchCircle(
                    cx=self._mm(geometry, "cx_mm"),
                    cy=self._mm(geometry, "cy_mm"),
                    radius=diameter / 2.0,
                    construction=construction,
                )
            )
        elif kind == "ARC":
            radius = self._mm(geometry, "radius_mm")
            start = radians(self._number(geometry, "start_deg"))
            end = radians(self._number(geometry, "end_deg"))
            if radius <= 0.0 or abs(end - start) <= 1e-7:
                raise WorkerError("Arc radius must be positive and its angles must differ.")
            created.append(
                SketchArc(
                    cx=self._mm(geometry, "cx_mm"),
                    cy=self._mm(geometry, "cy_mm"),
                    radius=radius,
                    start_angle=start,
                    end_angle=end,
                    construction=construction,
                )
            )
        elif kind == "RECTANGLE":
            x = self._mm(geometry, "x_mm")
            y = self._mm(geometry, "y_mm")
            width = self._mm(geometry, "width_mm")
            height = self._mm(geometry, "height_mm")
            if width <= 0.0 or height <= 0.0:
                raise WorkerError("Rectangle width and height must be greater than zero.")
            corners = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
            created = [
                SketchLine(
                    x1=start[0],
                    y1=start[1],
                    x2=end[0],
                    y2=end[1],
                    construction=construction,
                )
                for start, end in zip(corners, corners[1:] + corners[:1])
            ]
        else:
            raise WorkerError("geometry.type must be LINE, CIRCLE, ARC, or RECTANGLE.")
        sketch.entities.extend(created)
        sketch.deleted_regions.clear()
        self._save_document(document)
        return {"sketch_id": sketch.id, "entities": [entity_to_dict(item) for item in created]}

    def _update_geometry(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from blender_parametric_cad.core.serialization import entity_to_dict
        from blender_parametric_cad.sketch.entities import SketchArc, SketchCircle, SketchLine
        from blender_parametric_cad.sketch.numeric import set_arc, set_circle, set_rectangle

        document = self._document()
        _part, sketch = self._sketch_location(document, str(arguments.get("sketch_id") or ""))
        entity_id = str(arguments.get("entity_id") or "")
        entity = next((item for item in sketch.entities if item.id == entity_id), None)
        if entity is None:
            raise WorkerError(f"Sketch entity not found: {entity_id}")
        geometry = arguments.get("geometry")
        if not isinstance(geometry, dict):
            raise WorkerError("geometry must be an object.")
        kind = str(geometry.get("type") or entity.entity_type).upper()
        if kind == "LINE" and isinstance(entity, SketchLine):
            entity.x1 = self._mm(geometry, "x1_mm")
            entity.y1 = self._mm(geometry, "y1_mm")
            entity.x2 = self._mm(geometry, "x2_mm")
            entity.y2 = self._mm(geometry, "y2_mm")
        elif kind == "RECTANGLE" and isinstance(entity, SketchLine):
            set_rectangle(
                sketch,
                self._mm(geometry, "x_mm"),
                self._mm(geometry, "y_mm"),
                self._mm(geometry, "width_mm"),
                self._mm(geometry, "height_mm"),
                entity_id,
            )
        elif kind == "CIRCLE" and isinstance(entity, SketchCircle):
            diameter = self._mm(geometry, "diameter_mm")
            set_circle(sketch, self._mm(geometry, "cx_mm"), self._mm(geometry, "cy_mm"), diameter, entity_id)
        elif kind == "ARC" and isinstance(entity, SketchArc):
            set_arc(
                sketch,
                self._mm(geometry, "cx_mm"),
                self._mm(geometry, "cy_mm"),
                self._mm(geometry, "radius_mm"),
                radians(self._number(geometry, "start_deg")),
                radians(self._number(geometry, "end_deg")),
                entity_id,
            )
        else:
            raise WorkerError(f"Geometry type {kind} does not match entity {entity.entity_type}.")
        if "construction" in geometry:
            entity.construction = bool(geometry["construction"])
        sketch.deleted_regions.clear()
        self._save_document(document)
        return {"sketch_id": sketch.id, "entity": entity_to_dict(entity)}

    def _delete_geometry(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from blender_parametric_cad.core.serialization import entity_to_dict

        document = self._document()
        _part, sketch = self._sketch_location(document, str(arguments.get("sketch_id") or ""))
        entity_ids = arguments.get("entity_ids")
        if not isinstance(entity_ids, list) or not entity_ids:
            raise WorkerError("entity_ids must be a non-empty array.")
        wanted = {str(item) for item in entity_ids}
        removed = [entity for entity in sketch.entities if entity.id in wanted]
        if len(removed) != len(wanted):
            missing = sorted(wanted - {entity.id for entity in removed})
            raise WorkerError(f"Sketch entity not found: {', '.join(missing)}")
        sketch.entities = [entity for entity in sketch.entities if entity.id not in wanted]
        sketch.deleted_regions.clear()
        self._save_document(document)
        return {"sketch_id": sketch.id, "deleted": [entity_to_dict(item) for item in removed]}

    @staticmethod
    def _loop_payload(loop, deleted: set[str]) -> dict[str, Any]:
        circle = None
        if loop.circle is not None:
            circle = [loop.circle[0] * 1000.0, loop.circle[1] * 1000.0, loop.circle[2] * 1000.0]
        return {
            "region_id": loop.region_id,
            "entity_ids": list(loop.entity_ids),
            "points_mm": [[point[0] * 1000.0, point[1] * 1000.0] for point in loop.points],
            "circle_mm": circle,
            "deleted": loop.region_id in deleted,
        }

    def _profile(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from blender_parametric_cad.sketch.profile import ProfileDetector

        document = self._document()
        _part, sketch = self._sketch_location(document, str(arguments.get("sketch_id") or ""))
        detector = ProfileDetector()
        result = detector.detect(sketch)
        regions = detector.detect_regions(sketch)
        deleted = set(sketch.deleted_regions)
        profile = None
        if result.profile is not None:
            profile = {
                "kind": result.profile.kind,
                "region_ids": list(result.profile.region_ids),
                "points_mm": [[point[0] * 1000.0, point[1] * 1000.0] for point in result.profile.points],
                "circle_mm": (
                    [result.profile.circle[0] * 1000.0, result.profile.circle[1] * 1000.0, result.profile.circle[2] * 1000.0]
                    if result.profile.circle is not None
                    else None
                ),
            }
        return {
            "sketch_id": sketch.id,
            "success": result.success,
            "message": result.message,
            "profile": profile,
            "regions": [self._loop_payload(loop, deleted) for loop in regions],
            "deleted_regions": list(sketch.deleted_regions),
        }

    def _region_id(self, sketch, arguments: dict[str, Any]) -> str:
        from blender_parametric_cad.sketch.profile import ProfileDetector

        detector = ProfileDetector()
        regions = detector.detect_regions(sketch)
        region_id = arguments.get("region_id")
        if region_id:
            region_id = str(region_id)
            if not any(region.region_id == region_id for region in regions):
                raise WorkerError(f"Sketch region not found: {region_id}")
            return region_id
        if "region_index" not in arguments:
            raise WorkerError("Provide region_id or region_index.")
        try:
            index = int(arguments["region_index"])
        except (TypeError, ValueError) as exc:
            raise WorkerError("region_index must be an integer.") from exc
        if index < 0 or index >= len(regions):
            raise WorkerError(f"region_index is out of range: {index}")
        return regions[index].region_id

    def _delete_region(self, arguments: dict[str, Any]) -> dict[str, Any]:
        document = self._document()
        _part, sketch = self._sketch_location(document, str(arguments.get("sketch_id") or ""))
        region_id = self._region_id(sketch, arguments)
        if region_id not in sketch.deleted_regions:
            sketch.deleted_regions.append(region_id)
        self._save_document(document)
        return self._profile({"sketch_id": sketch.id})

    def _restore_region(self, arguments: dict[str, Any]) -> dict[str, Any]:
        document = self._document()
        _part, sketch = self._sketch_location(document, str(arguments.get("sketch_id") or ""))
        region_id = str(arguments.get("region_id") or "")
        if region_id in sketch.deleted_regions:
            sketch.deleted_regions.remove(region_id)
        self._save_document(document)
        return self._profile({"sketch_id": sketch.id})

    @staticmethod
    def _previous_body_feature(part, before_index: int):
        from blender_parametric_cad.features.extrude import ExtrudeFeature
        from blender_parametric_cad.features.revolve import RevolveFeature

        return next(
            (
                feature
                for feature in reversed(part.features[:before_index])
                if isinstance(feature, (ExtrudeFeature, RevolveFeature)) and not feature.suppressed
            ),
            None,
        )

    @classmethod
    def _dependencies(cls, part, sketch, operation: str, axis=None, before_index: int | None = None) -> list[str]:
        dependencies = [sketch.id]
        if axis is not None and axis.reference_type == "SKETCH_LINE" and axis.sketch_id not in dependencies:
            dependencies.append(axis.sketch_id)
        if operation != "NEW":
            previous = cls._previous_body_feature(part, len(part.features) if before_index is None else before_index)
            if previous is not None and previous.id not in dependencies:
                dependencies.append(previous.id)
        return dependencies

    @staticmethod
    def _operation(arguments: dict[str, Any]) -> str:
        operation = str(arguments.get("operation") or "").upper()
        if operation == "CUT":
            operation = "REMOVE"
        if operation not in {"NEW", "ADD", "REMOVE"}:
            raise WorkerError("operation must be NEW, ADD, or REMOVE.")
        return operation

    def _rebuild_payload(self, part_id: str) -> dict[str, Any]:
        from blender_parametric_cad.blender.adapter import rebuild_part

        result = rebuild_part(self.scene, part_id)
        self._autosave()
        part = self._document().get_part(part_id)
        return {
            "part_id": part_id,
            "success": result.success,
            "body_generated": result.body is not None,
            "errors": [
                {
                    "feature_id": error.feature_id,
                    "feature_name": error.feature_name,
                    "message": error.message,
                }
                for error in result.errors
            ],
            "features": [
                {
                    "id": feature.id,
                    "name": feature.name,
                    "feature_type": feature.feature_type,
                    "status": feature.status,
                    "error_message": feature.error_message,
                }
                for feature in (part.features if part is not None else [])
            ],
        }

    def _create_extrude(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from blender_parametric_cad.core.serialization import feature_to_dict
        from blender_parametric_cad.features.extrude import ExtrudeFeature
        from blender_parametric_cad.sketch.profile import ProfileDetector
        from blender_parametric_cad.sketch.sketch import SketchFeature

        document = self._document()
        part, sketch = self._sketch_location(document, str(arguments.get("sketch_id") or ""))
        if arguments.get("part_id") and str(arguments["part_id"]) != part.id:
            raise WorkerError("sketch_id does not belong to part_id.")
        detected = ProfileDetector().detect(sketch)
        if not detected.success:
            raise WorkerError(f"Cannot extrude {sketch.name}: {detected.message}")
        operation = self._operation(arguments)
        depth_mode = str(arguments.get("depth_mode") or "BLIND").upper()
        if depth_mode not in {"BLIND", "THROUGH_ALL"}:
            raise WorkerError("depth_mode must be BLIND or THROUGH_ALL.")
        try:
            distance = float(arguments["distance_mm"]) / 1000.0
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkerError("distance_mm must be numeric.") from exc
        direction = arguments.get("direction")
        if direction is None:
            direction = -1 if operation == "REMOVE" and depth_mode == "BLIND" and sketch.plane_reference.reference_type == "FEATURE_PLANE" else 1
        try:
            direction = int(direction)
        except (TypeError, ValueError) as exc:
            raise WorkerError("direction must be +1 or -1.") from exc
        if direction not in {-1, 1}:
            raise WorkerError("direction must be +1 or -1.")
        prefix = "Cut" if operation == "REMOVE" else "Extrude"
        feature = ExtrudeFeature(
            name=str(arguments.get("name") or part.next_feature_name(prefix)),
            sketch_id=sketch.id,
            distance=distance,
            direction=direction,
            operation=operation,
            depth_mode=depth_mode,
            dependencies=self._dependencies(part, sketch, operation),
        )
        part.add_feature(feature)
        document.active_part_id = part.id
        self._save_document(document)
        return {"part_id": part.id, "feature": feature_to_dict(feature), "rebuild": self._rebuild_payload(part.id)}

    def _axis_reference(self, axis_data: Any, part, sketch, axis_reverse: bool):
        from blender_parametric_cad.core.references import AxisReference
        from blender_parametric_cad.sketch.entities import SketchLine
        from blender_parametric_cad.sketch.sketch import SketchFeature

        direction = -1 if axis_reverse else 1
        if isinstance(axis_data, str):
            axis = axis_data.upper()
            if axis not in {"X", "Y", "Z"}:
                raise WorkerError("Datum revolve axis must be X, Y, or Z.")
            return AxisReference(axis=axis, direction=direction)
        if not isinstance(axis_data, dict):
            raise WorkerError("axis must be X/Y/Z or a SKETCH_LINE axis object.")
        reference_type = str(axis_data.get("type") or axis_data.get("reference_type") or "").upper()
        if reference_type in {"DATUM", "DATUM_AXIS"}:
            axis = str(axis_data.get("axis") or "").upper()
            if axis not in {"X", "Y", "Z"}:
                raise WorkerError("Datum revolve axis must be X, Y, or Z.")
            return AxisReference(axis=axis, direction=direction)
        if reference_type != "SKETCH_LINE":
            raise WorkerError("Only DATUM_AXIS and SKETCH_LINE revolve axes are supported.")
        axis_sketch_id = str(axis_data.get("sketch_id") or sketch.id)
        entity_id = str(axis_data.get("entity_id") or "")
        source_sketch = part.get_feature(axis_sketch_id)
        if not isinstance(source_sketch, SketchFeature):
            raise WorkerError(f"SketchLine axis source Sketch not found: {axis_sketch_id}")
        if not any(isinstance(entity, SketchLine) and entity.id == entity_id for entity in source_sketch.entities):
            raise WorkerError(f"SketchLine axis not found: {entity_id}")
        return AxisReference(
            reference_type="SKETCH_LINE",
            axis=None,
            sketch_id=axis_sketch_id,
            entity_id=entity_id,
            direction=direction,
        )

    def _create_revolve(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from blender_parametric_cad.core.serialization import feature_to_dict
        from blender_parametric_cad.features.revolve import RevolveFeature
        from blender_parametric_cad.sketch.profile import ProfileDetector

        document = self._document()
        part, sketch = self._sketch_location(document, str(arguments.get("sketch_id") or ""))
        if arguments.get("part_id") and str(arguments["part_id"]) != part.id:
            raise WorkerError("sketch_id does not belong to part_id.")
        operation = self._operation(arguments)
        try:
            angle = radians(float(arguments["angle_deg"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkerError("angle_deg must be numeric.") from exc
        if angle <= 0.0 or angle > 2.0 * pi + 1e-9:
            raise WorkerError("angle_deg must be greater than 0 and no more than 360.")
        axis = self._axis_reference(
            arguments.get("axis"),
            part,
            sketch,
            bool(arguments.get("axis_reverse", False)),
        )
        profile_entities = [
            entity
            for entity in sketch.entities
            if not entity.construction
            and not (axis.reference_type == "SKETCH_LINE" and entity.id == axis.entity_id)
        ]
        detected = ProfileDetector().detect_entities(profile_entities, sketch.deleted_regions)
        if not detected.success:
            raise WorkerError(f"Cannot revolve {sketch.name}: {detected.message}")
        feature = RevolveFeature(
            name=str(arguments.get("name") or part.next_feature_name("Revolve")),
            sketch_id=sketch.id,
            axis_reference=axis,
            angle=angle,
            operation=operation,
            dependencies=self._dependencies(part, sketch, operation, axis),
        )
        part.add_feature(feature)
        document.active_part_id = part.id
        self._save_document(document)
        return {"part_id": part.id, "feature": feature_to_dict(feature), "rebuild": self._rebuild_payload(part.id)}

    def _update_feature(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from blender_parametric_cad.core.serialization import feature_to_dict
        from blender_parametric_cad.features.extrude import ExtrudeFeature
        from blender_parametric_cad.features.revolve import RevolveFeature
        from blender_parametric_cad.sketch.sketch import SketchFeature

        document = self._document()
        feature_id = str(arguments.get("feature_id") or "")
        part, feature = self._feature_location(document, feature_id)
        if "name" in arguments:
            name = str(arguments["name"]).strip()
            if not name:
                raise WorkerError("Feature name cannot be empty.")
            feature.name = name
        if "suppressed" in arguments:
            feature.suppressed = bool(arguments["suppressed"])
        if isinstance(feature, ExtrudeFeature):
            sketch = part.get_feature(feature.sketch_id)
            if not isinstance(sketch, SketchFeature):
                raise WorkerError("Extrude source Sketch is unavailable.")
            if "distance_mm" in arguments:
                feature.distance = self._number(arguments, "distance_mm") / 1000.0
            if "direction" in arguments:
                direction = int(arguments["direction"])
                if direction not in {-1, 1}:
                    raise WorkerError("direction must be +1 or -1.")
                feature.direction = direction
            if "depth_mode" in arguments:
                feature.depth_mode = str(arguments["depth_mode"]).upper()
            if "operation" in arguments:
                feature.operation = self._operation(arguments)
            feature.dependencies = self._dependencies(
                part,
                sketch,
                "REMOVE" if feature.operation == "CUT" else feature.operation,
                before_index=part.get_feature_index(feature.id),
            )
        elif isinstance(feature, RevolveFeature):
            sketch = part.get_feature(feature.sketch_id)
            if not isinstance(sketch, SketchFeature):
                raise WorkerError("Revolve source Sketch is unavailable.")
            if "angle_deg" in arguments:
                angle = radians(self._number(arguments, "angle_deg"))
                if angle <= 0.0 or angle > 2.0 * pi + 1e-9:
                    raise WorkerError("angle_deg must be greater than 0 and no more than 360.")
                feature.angle = angle
            if "operation" in arguments:
                feature.operation = self._operation(arguments)
            if "axis" in arguments or "axis_reverse" in arguments:
                if "axis" in arguments:
                    axis_data = arguments["axis"]
                elif feature.axis_reference.reference_type == "SKETCH_LINE":
                    axis_data = {
                        "type": "SKETCH_LINE",
                        "sketch_id": feature.axis_reference.sketch_id,
                        "entity_id": feature.axis_reference.entity_id,
                    }
                else:
                    axis_data = feature.axis_reference.axis or "Z"
                feature.axis_reference = self._axis_reference(
                    axis_data,
                    part,
                    sketch,
                    bool(arguments.get("axis_reverse", feature.axis_reference.direction < 0)),
                )
            feature.dependencies = self._dependencies(
                part,
                sketch,
                feature.operation,
                feature.axis_reference,
                before_index=part.get_feature_index(feature.id),
            )
        else:
            raise WorkerError(f"Unsupported feature type: {feature.feature_type}")
        document.active_part_id = part.id
        self._save_document(document)
        return {"part_id": part.id, "feature": feature_to_dict(feature), "rebuild": self._rebuild_payload(part.id)}

    def _delete_feature(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from blender_parametric_cad.core.part import delete_feature
        from blender_parametric_cad.core.serialization import feature_to_dict

        document = self._document()
        part, _feature = self._feature_location(document, str(arguments.get("feature_id") or ""))
        deleted = delete_feature(part, str(arguments["feature_id"]))
        self._save_document(document)
        return {
            "part_id": part.id,
            "deleted": [feature_to_dict(feature) for feature in deleted],
            "rebuild": self._rebuild_payload(part.id),
        }

    def _suppress_feature(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._update_feature(arguments)

    def _rollback(self, arguments: dict[str, Any]) -> dict[str, Any]:
        document = self._document()
        feature_id = str(arguments.get("feature_id") or "")
        if not feature_id:
            part = document.active_part
            if part is None:
                raise WorkerError("No active Part Studio.")
            part.rollback_index = None
        else:
            part, _feature = self._feature_location(document, feature_id)
            index = part.get_feature_index(feature_id)
            if index is None:
                raise WorkerError(f"Feature not found: {feature_id}")
            part.rollback_index = index
        self._save_document(document)
        return {"part_id": part.id, "rollback_index": part.rollback_index, "rebuild": self._rebuild_payload(part.id)}

    def _rebuild(self, arguments: dict[str, Any]) -> dict[str, Any]:
        document = self._document()
        part = self._part(document, arguments)
        return self._rebuild_payload(part.id)

    def _export_part(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from blender_parametric_cad.blender.adapter import export_part

        document = self._document()
        part = self._part(document, arguments)
        filepath = str(arguments.get("filepath") or "")
        file_format = str(arguments.get("file_format") or "STL").upper()
        try:
            path = export_part(self.scene, part.id, filepath, file_format)
        except (RuntimeError, ValueError) as exc:
            raise WorkerError(str(exc)) from exc
        self._autosave()
        return {"part_id": part.id, "file_format": file_format, "filepath": path}

    def _save_scene(self, arguments: dict[str, Any]) -> dict[str, Any]:
        filepath = str(arguments.get("filepath") or self._bpy.data.filepath or "")
        if not filepath:
            raise WorkerError("filepath is required when the Blender file has not been saved yet.")
        status = self._bpy.ops.wm.save_as_mainfile(filepath=filepath)
        if "FINISHED" not in status:
            raise WorkerError(f"Could not save Blender file: {filepath}")
        self.autosave_path = filepath
        return {"filepath": str(Path(filepath).expanduser())}


def _script_arguments() -> list[str]:
    try:
        separator = sys.argv.index("--")
    except ValueError:
        return []
    return sys.argv[separator + 1 :]


def _parser():
    parser = argparse.ArgumentParser(description="Blender Parametric CAD MCP worker")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--token", required=True)
    parser.add_argument("--blend-file")
    parser.add_argument("--autosave")
    return parser


def _send(stream, message: dict[str, Any]) -> None:
    stream.write(json.dumps(message, ensure_ascii=False).encode("utf-8"))
    stream.write(b"\n")
    stream.flush()


def main() -> int:
    args = _parser().parse_args(_script_arguments())
    worker = BlenderCadWorker(args.blend_file, args.autosave)
    with socket.create_connection((args.host, args.port), timeout=30.0) as connection:
        connection.settimeout(None)
        reader = connection.makefile("rb")
        writer = connection.makefile("wb")
        _send(writer, {"type": "hello", "token": args.token})
        for line in reader:
            if not line.strip():
                continue
            request = None
            try:
                request = json.loads(line.decode("utf-8"))
                if not isinstance(request, dict):
                    raise WorkerError("Worker message must be a JSON object.")
                if request.get("token") != args.token:
                    raise WorkerError("Authentication failed.")
                method = request.get("method")
                if method == "shutdown":
                    _send(writer, {"id": request.get("id"), "ok": True, "result": {}})
                    break
                if method != "tool":
                    raise WorkerError(f"Unknown worker method: {method}")
                result = worker.handle(request.get("name"), request.get("arguments") or {})
                _send(writer, {"id": request.get("id"), "ok": True, "result": result})
            except Exception as exc:
                _send(
                    writer,
                    {
                        "id": request.get("id") if isinstance(request, dict) else None,
                        "ok": False,
                        "error": str(exc),
                    },
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
