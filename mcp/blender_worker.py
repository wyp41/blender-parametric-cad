"""Blender-side JSON worker used by :mod:`mcp.server`.

This file is launched once by the stdio MCP bridge with Blender 5.1.2.  In the
default visible mode, requests are polled through ``bpy.app.timers`` so the
normal Blender window remains responsive and shows each rebuild.  Headless mode
keeps the legacy blocking loop for CI.  All calls run on Blender's main thread,
so the existing ``bpy`` adapter and mesh backend remain the source of truth. The
worker never prints to stdout except for protocol messages; Blender's process
output is discarded by the parent bridge.
"""

from __future__ import annotations

import argparse
import ast
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import errno
import importlib
from io import StringIO
import json
from math import isfinite, pi, radians
import os
from pathlib import Path
import secrets
import socket
import sys
import traceback
from typing import Any


def _extension_package_name(package_root: Path) -> str:
    """Resolve the package name Blender assigned to this extension.

    Blender loads extensions through a junction package such as
    ``bl_ext.user_default.blender_parametric_cad``.  A worker launched with
    ``blender --python`` is still a script, so it must opt into that qualified
    name before importing any CAD modules.  Importing the same files as a
    bare ``blender_parametric_cad`` package pollutes Blender's global module
    namespace and triggers the Extensions policy warnings shown in
    Preferences.
    """

    package_id = package_root.name
    current_package = globals().get("__package__")
    if current_package:
        candidate = str(current_package).rsplit(".", 1)[0]
        if candidate.rsplit(".", 1)[-1] == package_id:
            return candidate

    # A worker can be launched before this extension itself is enabled.  The
    # junction repository modules may not be in ``sys.modules`` yet, but
    # Blender's preferences still identify the repository that contains this
    # package (including symlinked checkouts).
    try:
        import bpy

        repositories = getattr(
            getattr(getattr(bpy, "context", None), "preferences", None),
            "extensions",
            None,
        )
        for repository in getattr(repositories, "repos", ()):
            repository_path = str(getattr(repository, "directory", "")).strip()
            if not repository_path:
                continue
            repository_dir = Path(repository_path).expanduser()
            try:
                if (repository_dir / package_id).resolve() == package_root.resolve():
                    repository_id = str(getattr(repository, "module", "")).strip()
                    if repository_id:
                        return f"bl_ext.{repository_id}.{package_id}"
            except (OSError, RuntimeError):
                continue
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError):
        pass

    # Installed extensions live at ``.../extensions/<repository>/<package>``.
    # Deriving the repository ID from the path keeps this compatible with
    # Blender's default and user-created repositories.
    parts = package_root.parts
    for index in range(len(parts) - 3, -1, -1):
        if parts[index] == "extensions" and parts[index + 2] == package_id:
            return f"bl_ext.{parts[index + 1]}.{package_id}"
    return package_id


def _has_package_context(package_root: Path) -> bool:
    current_package = globals().get("__package__")
    if not current_package:
        return False
    candidate = str(current_package).rsplit(".", 1)[0]
    return candidate.rsplit(".", 1)[-1] == package_root.name


def _prepare_package() -> tuple[Path, str]:
    package_root = Path(__file__).resolve().parent.parent
    package_name = _extension_package_name(package_root)
    if _has_package_context(package_root):
        return package_root, package_name

    if package_name.startswith("bl_ext."):
        # The Blender startup sequence registers the ``bl_ext`` junction
        # package before executing --python scripts.  Importing through it
        # keeps every bundled module inside the extension namespace.
        try:
            importlib.import_module(package_name)
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                f"Could not import Blender extension package {package_name!r}."
            ) from exc
    else:
        # Direct source-checkout execution is useful for development and
        # tests.  The checkout is outside an Extensions repository, so this
        # fallback does not affect Blender's extension namespace policy.
        parent = package_root.parent
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
        importlib.import_module(package_name)
    return package_root, package_name


PACKAGE_ROOT, PACKAGE_NAME = _prepare_package()
if not _has_package_context(PACKAGE_ROOT):
    # Relative imports below now resolve to the qualified extension package
    # even though this file was launched as ``__main__``.
    __package__ = f"{PACKAGE_NAME}.mcp"


from .endpoint import (  # noqa: E402  (package bootstrap must run first)
    endpoint_is_reachable,
    endpoint_lock,
    endpoint_path,
    read_endpoint,
    remove_endpoint,
    write_endpoint,
)


_EMBEDDED_SERVICE = None


def _endpoint_is_current_process(endpoint: dict[str, Any] | None) -> bool:
    try:
        return int(endpoint.get("pid")) == os.getpid() if endpoint else False
    except (TypeError, ValueError):
        return False


class WorkerError(RuntimeError):
    """A user-correctable CAD worker error with a machine-readable code."""

    def __init__(self, message: str, code: str = "CAD_ERROR", details: Any = None):
        super().__init__(message)
        self.code = code
        self.details = details


class BlenderCadWorker:
    """Dispatch CAD tools and trusted Python inside one Blender process."""

    def __init__(self, blend_file: str | None = None, autosave: str | None = None):
        self._bpy = self._load_blender_runtime()
        self._console_namespace = {"__name__": "__main__", "bpy": self._bpy}
        self._registered_properties = self._ensure_scene_properties()
        self.autosave_path = autosave or blend_file
        if blend_file:
            path = Path(blend_file).expanduser()
            if path.exists():
                status = self._bpy.ops.wm.open_mainfile(filepath=str(path))
                if "FINISHED" not in status:
                    raise WorkerError(f"Could not open Blender file: {path}")
        # Rehydrate generated results and validate the restored document even
        # in MCP-only sessions where the interactive add-on UI is not loaded.
        from ..blender import adapter

        adapter.register_handlers()

    @staticmethod
    def _load_blender_runtime():
        try:
            import bpy
        except ImportError as exc:  # pragma: no cover - only Blender supplies bpy.
            raise WorkerError("The MCP worker must be launched by Blender 5.1.2.") from exc
        return bpy

    def _ensure_scene_properties(self) -> bool:
        from ..blender import properties

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
            "blender_execute_python": self._execute_python,
            "cad_status": self._status,
            "cad_create_part": self._create_part,
            "cad_set_active_part": self._set_active_part,
            "cad_delete_part": self._delete_part,
            "cad_create_sketch": self._create_sketch,
            "cad_add_geometry": self._add_geometry,
            "cad_sketch_add_line": self._sketch_add_line,
            "cad_sketch_add_circle": self._sketch_add_circle,
            "cad_sketch_add_rectangle": self._sketch_add_rectangle,
            "cad_sketch_update_rectangle": self._sketch_update_rectangle,
            "cad_sketch_add_constraint": self._sketch_add_constraint,
            "cad_sketch_delete_constraint": self._sketch_delete_constraint,
            "cad_sketch_add_dimension": self._sketch_add_dimension,
            "cad_sketch_update_dimension": self._sketch_update_dimension,
            "cad_sketch_delete_dimension": self._sketch_delete_dimension,
            "cad_get_sketch": self._get_sketch,
            "cad_get_history": self._get_history,
            "cad_get_edges": self._get_edges,
            "cad_list_references": self._list_references,
            "cad_inspect_geometry": self._inspect_geometry,
            "cad_get_document": self._get_document,
            "cad_get_part_studio": self._get_part_studio,
            "cad_get_feature": self._get_feature,
            "cad_update_geometry": self._update_geometry,
            "cad_delete_geometry": self._delete_geometry,
            "cad_profile": self._profile,
            "cad_delete_region": self._delete_region,
            "cad_restore_region": self._restore_region,
            "cad_create_extrude": self._create_extrude,
            "cad_create_revolve": self._create_revolve,
            "cad_create_transform": self._create_transform,
            "cad_create_mirror": self._create_mirror,
            "cad_create_chamfer": self._create_chamfer,
            "cad_create_fillet": self._create_fillet,
            "cad_update_feature": self._update_feature,
            "cad_delete_feature": self._delete_feature,
            "cad_suppress_feature": self._suppress_feature,
            "cad_rollback": self._rollback,
            "cad_rebuild": self._rebuild,
            "cad_validate_document": self._validate_document,
            "cad_export_part": self._export_part,
            "cad_save_scene": self._save_scene,
        }
        if name not in handlers:
            raise WorkerError(f"Unknown CAD tool: {name}")
        if not isinstance(arguments, dict):
            raise WorkerError("Tool arguments must be an object.")
        try:
            return handlers[name](arguments)
        finally:
            # MCP calls run from a timer rather than an operator context. Tag
            # every 3D View for redraw so sketch overlays and result meshes are
            # visible immediately after the response is produced.
            self._tag_viewports()

    def _execute_python(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run trusted Python in a persistent Blender-console-like namespace."""

        code = arguments.get("code")
        if not isinstance(code, str) or not code.strip():
            raise WorkerError("code must be a non-empty string.")

        filename = "<blender_execute_python>"
        stdout = StringIO()
        stderr = StringIO()
        namespace = self._console_namespace
        try:
            tree = ast.parse(code, filename=filename, mode="exec")
            result = None
            with redirect_stdout(stdout), redirect_stderr(stderr):
                if tree.body and isinstance(tree.body[-1], ast.Expr):
                    final_expression = tree.body.pop()
                    if tree.body:
                        exec(compile(tree, filename, "exec"), namespace, namespace)
                    expression = ast.Expression(final_expression.value)
                    ast.copy_location(expression, final_expression)
                    ast.fix_missing_locations(expression)
                    result = eval(compile(expression, filename, "eval"), namespace, namespace)
                else:
                    exec(compile(tree, filename, "exec"), namespace, namespace)
        except BaseException as exc:
            details = traceback.format_exc().rstrip()
            output = stdout.getvalue()
            errors = stderr.getvalue()
            message = f"Blender Python execution failed:\n{details}"
            if output:
                message += f"\nstdout:\n{output.rstrip()}"
            if errors:
                message += f"\nstderr:\n{errors.rstrip()}"
            raise WorkerError(message) from exc

        try:
            result_repr = repr(result) if result is not None else None
        except BaseException:
            result_repr = f"<{type(result).__name__} repr unavailable>"
        return {
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
            "result": result_repr,
        }

    def _tag_viewports(self) -> None:
        try:
            windows = self._bpy.context.window_manager.windows
        except (AttributeError, ReferenceError, RuntimeError):
            return
        for window in windows:
            screen = getattr(window, "screen", None)
            if screen is None:
                continue
            for area in screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()

    def _document(self):
        from ..blender.adapter import load_document_from_scene

        return load_document_from_scene(self.scene)

    def _save_document(self, document) -> None:
        from ..blender.adapter import save_document_to_scene

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
            raise WorkerError(
                "Part Studio not found. Create one with cad_create_part.",
                "REFERENCE_MISSING",
            )
        return part

    @staticmethod
    def _feature_location(document, feature_id: str):
        if not feature_id:
            raise WorkerError("A feature_id is required.", "INVALID_REFERENCE")
        for part in document.parts:
            feature = part.get_feature(feature_id)
            if feature is not None:
                return part, feature
        raise WorkerError(f"Feature not found: {feature_id}", "REFERENCE_MISSING")

    @staticmethod
    def _sketch_location(document, sketch_id: str):
        from ..sketch.sketch import SketchFeature

        part, feature = BlenderCadWorker._feature_location(document, sketch_id)
        if not isinstance(feature, SketchFeature):
            raise WorkerError(
                f"Feature is not a Sketch: {sketch_id}", "INVALID_REFERENCE"
            )
        return part, feature

    def _commit_sketch_candidate(self, previous, candidate, part_id: str):
        """Save and rebuild a candidate, restoring the previous document on failure."""

        self._save_document(candidate)
        rebuild = self._rebuild_payload(part_id)
        if rebuild["success"]:
            return rebuild
        self._save_document(previous)
        self._rebuild_payload(part_id)
        message = "; ".join(item["message"] for item in rebuild["errors"])
        raise WorkerError(
            message or "Sketch mutation could not rebuild the Part Studio.",
            code="REBUILD_FAILED",
            details={"rebuild": rebuild},
        )

    @staticmethod
    def _sketch_reference(sketch_id: str, value: Any, default_sub_element: str | None = None):
        from ..core.references import SketchEntityReference

        if not isinstance(value, dict):
            raise WorkerError("Each Sketch reference must be an object.", "INVALID_REFERENCE")
        entity_id = str(value.get("entity_id") or "")
        if not entity_id:
            raise WorkerError("Sketch references require entity_id.", "INVALID_REFERENCE")
        reference_sketch_id = str(value.get("sketch_id") or sketch_id)
        sub_element = value.get("sub_element", default_sub_element)
        try:
            return SketchEntityReference(reference_sketch_id, entity_id, sub_element)
        except (TypeError, ValueError) as exc:
            raise WorkerError(str(exc), "INVALID_REFERENCE") from exc

    def _sketch_references(self, sketch_id: str, values: Any):
        if not isinstance(values, list) or not values:
            raise WorkerError("entity_refs must be a non-empty array.", "INVALID_REFERENCE")
        return [self._sketch_reference(sketch_id, value) for value in values]

    @staticmethod
    def _solver_failure(result):
        from ..sketch.solver import CONFLICT, INVALID_REFERENCE

        code = "CONSTRAINT_CONFLICT" if result.status == CONFLICT else "INVALID_REFERENCE"
        return WorkerError(result.message or result.status, code=code)

    def _solve_candidate(self, sketch):
        from ..sketch.solver import SketchSolver

        result = SketchSolver().solve(sketch)
        if not result.success:
            raise self._solver_failure(result)
        return result

    def _status(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        from ..core.serialization import document_to_dict

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
        from ..core.part import Part
        from ..core.serialization import document_to_dict

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
        from ..core.serialization import document_to_dict

        document = self._document()
        part_id = str(arguments.get("part_id") or "")
        document.set_active_part(part_id)
        self._save_document(document)
        return {"active_part_id": document.active_part_id, "document": document_to_dict(document)}

    def _delete_part(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ..blender.adapter import remove_part_geometry
        from ..core.serialization import document_to_dict

        document = self._document()
        part_id = str(arguments.get("part_id") or "")
        removed = document.remove_part(part_id)
        if removed is None:
            raise WorkerError(f"Part Studio not found: {part_id}")
        remove_part_geometry(part_id)
        self._save_document(document)
        return {"deleted_part_id": part_id, "document": document_to_dict(document)}

    def _create_sketch(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ..core.references import TopoReference
        from ..core.serialization import feature_to_dict
        from ..sketch.sketch import SketchFeature

        document = self._document()
        part = self._part(document, arguments)
        name = str(arguments.get("name") or "").strip()
        if not name:
            name = part.next_feature_name("Sketch")
        face_data = arguments.get("face_reference")
        feature_id = arguments.get("feature_id")
        try:
            offset_mm = float(arguments.get("offset_mm", 0.0) or 0.0)
        except (TypeError, ValueError) as exc:
            raise WorkerError("offset_mm must be numeric.") from exc
        if not isfinite(offset_mm):
            raise WorkerError("offset_mm must be finite.")
        offset = offset_mm / 1000.0
        if face_data is not None:
            if not isinstance(face_data, dict):
                raise WorkerError("face_reference must be an object.")
            try:
                sketch = SketchFeature.on_face(
                    name, TopoReference.from_dict(face_data), offset=offset
                )
            except (TypeError, ValueError, KeyError) as exc:
                raise WorkerError(f"Invalid face_reference: {exc}") from exc
        elif feature_id:
            role = str(arguments.get("role") or "END_PLANE")
            sketch = SketchFeature.on_feature_plane(
                name, str(feature_id), role, offset=offset
            )
        else:
            plane = str(arguments.get("plane") or "XY").upper()
            try:
                sketch = SketchFeature.on_plane(name, plane, offset=offset)
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

    @staticmethod
    def _vector(arguments: dict[str, Any], key: str) -> tuple[float, float, float]:
        value = arguments.get(key)
        if value is None:
            return (0.0, 0.0, 0.0)
        if isinstance(value, dict):
            values = (value.get("x", 0.0), value.get("y", 0.0), value.get("z", 0.0))
        elif isinstance(value, (list, tuple)) and len(value) == 3:
            values = tuple(value)
        else:
            raise WorkerError(f"{key} must contain numeric x, y, and z values.")
        try:
            result = tuple(float(item) for item in values)
        except (TypeError, ValueError) as exc:
            raise WorkerError(f"{key} must contain numeric x, y, and z values.") from exc
        if not all(isfinite(value) for value in result):
            raise WorkerError(f"{key} must contain finite x, y, and z values.")
        return result  # type: ignore[return-value]

    def _add_geometry(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ..core.serialization import entity_to_dict
        from ..core.references import SketchEntityReference
        from ..sketch.constraints import SketchConstraint, constraint_to_dict
        from ..sketch.dimensions import LENGTH, SketchDimension, dimension_to_dict
        from ..sketch.entities import SketchArc, SketchCircle, SketchLine
        from ..sketch.primitives import RectangleDefinition

        document = self._document()
        previous = deepcopy(document)
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
            if not all(isfinite(value) for value in (x, y, width, height)):
                raise WorkerError("Rectangle coordinates and dimensions must be finite.", "INVALID_RECTANGLE")
            if width <= 0.0 or height <= 0.0:
                raise WorkerError("Rectangle width and height must be greater than zero.", "INVALID_RECTANGLE")
            if any(not entity.construction for entity in sketch.entities):
                raise WorkerError(
                    "A semantic rectangle must be created in an otherwise empty Sketch.",
                    "INVALID_RECTANGLE",
                )
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
        auto_constraints = []
        rectangle_definition = None
        rectangle_dimensions = []
        if kind == "RECTANGLE":
            for index, entity in enumerate(created):
                next_entity = created[(index + 1) % len(created)]
                constraint = SketchConstraint(
                    constraint_type="COINCIDENT",
                    entity_refs=[
                        SketchEntityReference(sketch.id, entity.id, "END"),
                        SketchEntityReference(sketch.id, next_entity.id, "START"),
                    ],
                )
                sketch.constraints.append(constraint)
                auto_constraints.append(constraint)
            width_dimension = SketchDimension(
                dimension_type=LENGTH,
                entity_refs=[SketchEntityReference(sketch.id, created[0].id)],
                value=width,
                driving=True,
            )
            height_dimension = SketchDimension(
                dimension_type=LENGTH,
                entity_refs=[SketchEntityReference(sketch.id, created[1].id)],
                value=height,
                driving=True,
            )
            sketch.dimensions.extend((width_dimension, height_dimension))
            rectangle_dimensions.extend((width_dimension, height_dimension))
            rectangle_definition = RectangleDefinition(
                bottom_line_id=created[0].id,
                right_line_id=created[1].id,
                top_line_id=created[2].id,
                left_line_id=created[3].id,
                width_dimension_id=width_dimension.id,
                height_dimension_id=height_dimension.id,
            )
            sketch.rectangles.append(rectangle_definition)
        sketch.deleted_regions.clear()
        solver = self._solve_candidate(sketch)
        rebuild = self._commit_sketch_candidate(previous, document, _part.id)
        return {
            "ok": True,
            "sketch_id": sketch.id,
            "entities": [entity_to_dict(item) for item in created],
            "constraint_ids": [item.id for item in auto_constraints],
            "constraints": [constraint_to_dict(item) for item in auto_constraints],
            "dimensions": [dimension_to_dict(item) for item in rectangle_dimensions],
            "rectangle_id": rectangle_definition.id if rectangle_definition else None,
            "width_dimension_id": (
                rectangle_definition.width_dimension_id
                if rectangle_definition is not None else None
            ),
            "height_dimension_id": (
                rectangle_definition.height_dimension_id
                if rectangle_definition is not None else None
            ),
            "solver_status": solver.status,
            "rebuild": rebuild,
        }

    def _sketch_add_line(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._add_geometry(
            {
                "sketch_id": arguments.get("sketch_id"),
                "geometry": {
                    "type": "LINE",
                    "x1_mm": arguments.get("x1_mm"),
                    "y1_mm": arguments.get("y1_mm"),
                    "x2_mm": arguments.get("x2_mm"),
                    "y2_mm": arguments.get("y2_mm"),
                    "construction": arguments.get("construction", False),
                },
            }
        )
        entity = result["entities"][0]
        return {
            "ok": True,
            "sketch_id": result["sketch_id"],
            "entity_id": entity["id"],
            "entity_type": entity["entity_type"],
            "entity": entity,
            "solver_status": result["solver_status"],
            "rebuild_status": "OK",
            "rebuild": result["rebuild"],
        }

    def _sketch_add_circle(self, arguments: dict[str, Any]) -> dict[str, Any]:
        geometry = {
            "type": "CIRCLE",
            "cx_mm": arguments.get("cx_mm"),
            "cy_mm": arguments.get("cy_mm"),
            "construction": arguments.get("construction", False),
        }
        if "diameter_mm" in arguments:
            geometry["diameter_mm"] = arguments["diameter_mm"]
        elif "radius_mm" in arguments:
            geometry["radius_mm"] = arguments["radius_mm"]
        else:
            raise WorkerError("Provide diameter_mm or radius_mm.", "INVALID_GEOMETRY")
        result = self._add_geometry(
            {
                "sketch_id": arguments.get("sketch_id"),
                "geometry": geometry,
            }
        )
        entity = result["entities"][0]
        return {
            "ok": True,
            "sketch_id": result["sketch_id"],
            "entity_id": entity["id"],
            "entity_type": entity["entity_type"],
            "entity": entity,
            "solver_status": result["solver_status"],
            "rebuild_status": "OK",
            "rebuild": result["rebuild"],
        }

    def _sketch_add_rectangle(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._add_geometry(
            {
                "sketch_id": arguments.get("sketch_id"),
                "geometry": {
                    "type": "RECTANGLE",
                    "x_mm": arguments.get("x_mm", 0.0),
                    "y_mm": arguments.get("y_mm", 0.0),
                    "width_mm": arguments.get("width_mm"),
                    "height_mm": arguments.get("height_mm"),
                    "construction": arguments.get("construction", False),
                },
            }
        )
        entities = result["entities"]
        names = ("bottom", "right", "top", "left")
        return {
            "ok": True,
            "sketch_id": result["sketch_id"],
            "rectangle_id": result.get("rectangle_id"),
            "entity_ids": {name: entity["id"] for name, entity in zip(names, entities)},
            "entities": entities,
            "constraint_ids": result.get("constraint_ids", []),
            "width_dimension_id": result.get("width_dimension_id"),
            "height_dimension_id": result.get("height_dimension_id"),
            "solver_status": result["solver_status"],
            "rebuild_status": "OK",
            "rebuild": result["rebuild"],
        }

    def _sketch_update_rectangle(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Update a semantic rectangle without replacing any line UUIDs."""

        from ..core.serialization import entity_to_dict
        from ..sketch.numeric import (
            rectangle_definition_for,
            rectangle_parameters_by_id,
            set_rectangle,
        )

        document = self._document()
        previous = deepcopy(document)
        part, sketch = self._sketch_location(
            document, str(arguments.get("sketch_id") or "")
        )
        rectangle_id = str(arguments.get("rectangle_id") or "")
        definition = rectangle_definition_for(sketch, rectangle_id=rectangle_id)
        if definition is None:
            raise WorkerError(
                f"Rectangle not found: {rectangle_id}", "REFERENCE_MISSING"
            )
        current = rectangle_parameters_by_id(sketch, definition.id)
        if current is None:
            raise WorkerError(
                "Rectangle geometry or semantic line references are missing.",
                "INVALID_RECTANGLE",
            )
        values = list(current)
        keys = ("x_mm", "y_mm", "width_mm", "height_mm")
        for index, key in enumerate(keys):
            if key not in arguments:
                continue
            try:
                value = float(arguments[key]) / 1000.0
            except (TypeError, ValueError) as exc:
                raise WorkerError(f"{key} must be numeric.", "INVALID_RECTANGLE") from exc
            if not isfinite(value):
                raise WorkerError(f"{key} must be finite.", "INVALID_RECTANGLE")
            values[index] = value
        if values[2] <= 0.0 or values[3] <= 0.0:
            raise WorkerError(
                "Rectangle width and height must be greater than zero.",
                "INVALID_RECTANGLE",
            )
        try:
            set_rectangle(sketch, *values, entity_id=definition.bottom_line_id)
        except (TypeError, ValueError) as exc:
            raise WorkerError(str(exc), "INVALID_RECTANGLE") from exc
        sketch.deleted_regions.clear()
        solver = self._solve_candidate(sketch)
        rebuild = self._commit_sketch_candidate(previous, document, part.id)
        updated_definition = rectangle_definition_for(sketch, rectangle_id=definition.id)
        return {
            "ok": True,
            "sketch_id": sketch.id,
            "rectangle_id": definition.id,
            "entity_ids": dict(
                zip(
                    ("bottom", "right", "top", "left"),
                    definition.entity_ids,
                )
            ),
            "entities": [
                entity_to_dict(entity)
                for entity in sketch.entities
                if entity.id in definition.entity_ids
            ],
            "x_mm": values[0] * 1000.0,
            "y_mm": values[1] * 1000.0,
            "width_mm": values[2] * 1000.0,
            "height_mm": values[3] * 1000.0,
            "width_dimension_id": definition.width_dimension_id,
            "height_dimension_id": definition.height_dimension_id,
            "solver_status": solver.status,
            "rebuild_status": "OK" if rebuild["success"] else "BLOCKED",
            "rebuild": rebuild,
        }

    def _sketch_add_constraint(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ..sketch.constraints import SketchConstraint, constraint_to_dict, validate_constraint

        document = self._document()
        previous = deepcopy(document)
        part, sketch = self._sketch_location(document, str(arguments.get("sketch_id") or ""))
        refs = self._sketch_references(sketch.id, arguments.get("entity_refs"))
        try:
            constraint = SketchConstraint(
                id=str(arguments.get("constraint_id") or "") or None,
                constraint_type=str(arguments.get("constraint_type") or ""),
                entity_refs=refs,
                enabled=bool(arguments.get("enabled", True)),
            )
        except (TypeError, ValueError) as exc:
            raise WorkerError(str(exc), "INVALID_REFERENCE") from exc
        if any(item.id == constraint.id for item in sketch.constraints):
            raise WorkerError(
                f"Sketch constraint already exists: {constraint.id}",
                "INVALID_REFERENCE",
            )
        try:
            validate_constraint(sketch, constraint)
        except Exception as exc:
            raise WorkerError(str(exc), "INVALID_REFERENCE") from exc
        sketch.constraints.append(constraint)
        solver = self._solve_candidate(sketch)
        rebuild = self._commit_sketch_candidate(previous, document, part.id)
        return {
            "ok": True,
            "sketch_id": sketch.id,
            "constraint_id": constraint.id,
            "constraint": constraint_to_dict(constraint),
            "status": solver.status,
            "solver_status": solver.status,
            "rebuild_status": "OK",
            "rebuild": rebuild,
        }

    def _sketch_delete_constraint(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ..sketch.constraints import constraint_to_dict

        document = self._document()
        previous = deepcopy(document)
        part, sketch = self._sketch_location(document, str(arguments.get("sketch_id") or ""))
        constraint_id = str(arguments.get("constraint_id") or "")
        index = next(
            (index for index, item in enumerate(sketch.constraints) if item.id == constraint_id),
            None,
        )
        if index is None:
            raise WorkerError(f"Sketch constraint not found: {constraint_id}", "INVALID_REFERENCE")
        deleted = sketch.constraints.pop(index)
        solver = self._solve_candidate(sketch)
        rebuild = self._commit_sketch_candidate(previous, document, part.id)
        return {
            "ok": True,
            "sketch_id": sketch.id,
            "deleted_constraint": constraint_to_dict(deleted),
            "solver_status": solver.status,
            "rebuild_status": "OK",
            "rebuild": rebuild,
        }

    def _sketch_add_dimension(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ..sketch.dimensions import SketchDimension, dimension_to_dict, validate_dimension_conflicts

        document = self._document()
        previous = deepcopy(document)
        part, sketch = self._sketch_location(document, str(arguments.get("sketch_id") or ""))
        try:
            value_mm = float(arguments["value_mm"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkerError("value_mm must be numeric.", "INVALID_DIMENSION") from exc
        refs = self._sketch_references(sketch.id, arguments.get("entity_refs"))
        try:
            dimension = SketchDimension(
                id=str(arguments.get("dimension_id") or "") or None,
                dimension_type=str(arguments.get("dimension_type") or ""),
                entity_refs=refs,
                value=value_mm / 1000.0,
                driving=bool(arguments.get("driving", True)),
            )
        except (TypeError, ValueError) as exc:
            raise WorkerError(str(exc), "INVALID_DIMENSION") from exc
        if any(item.id == dimension.id for item in sketch.dimensions):
            raise WorkerError(
                f"Sketch dimension already exists: {dimension.id}",
                "INVALID_DIMENSION",
            )
        try:
            validate_dimension_conflicts(sketch, dimension)
        except Exception as exc:
            raise WorkerError(str(exc), "CONSTRAINT_CONFLICT") from exc
        sketch.dimensions.append(dimension)
        solver = self._solve_candidate(sketch)
        rebuild = self._commit_sketch_candidate(previous, document, part.id)
        return {
            "ok": True,
            "sketch_id": sketch.id,
            "dimension_id": dimension.id,
            "dimension": dimension_to_dict(dimension),
            "value_mm": dimension.value * 1000.0,
            "status": solver.status,
            "solver_status": solver.status,
            "rebuild_status": "OK",
            "rebuild": rebuild,
        }

    def _sketch_update_dimension(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ..sketch.dimensions import dimension_to_dict

        document = self._document()
        previous = deepcopy(document)
        part, sketch = self._sketch_location(document, str(arguments.get("sketch_id") or ""))
        dimension_id = str(arguments.get("dimension_id") or "")
        dimension = next((item for item in sketch.dimensions if item.id == dimension_id), None)
        if dimension is None:
            raise WorkerError(f"Sketch dimension not found: {dimension_id}", "INVALID_DIMENSION")
        try:
            dimension.value = float(arguments["value_mm"]) / 1000.0
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkerError("value_mm must be numeric.", "INVALID_DIMENSION") from exc
        solver = self._solve_candidate(sketch)
        rebuild = self._commit_sketch_candidate(previous, document, part.id)
        return {
            "ok": True,
            "sketch_id": sketch.id,
            "dimension_id": dimension.id,
            "dimension": dimension_to_dict(dimension),
            "value_mm": dimension.value * 1000.0,
            "status": solver.status,
            "solver_status": solver.status,
            "rebuild_status": "OK",
            "rebuild": rebuild,
        }

    def _sketch_delete_dimension(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ..sketch.dimensions import dimension_to_dict

        document = self._document()
        previous = deepcopy(document)
        part, sketch = self._sketch_location(document, str(arguments.get("sketch_id") or ""))
        dimension_id = str(arguments.get("dimension_id") or "")
        index = next(
            (index for index, item in enumerate(sketch.dimensions) if item.id == dimension_id),
            None,
        )
        if index is None:
            raise WorkerError(f"Sketch dimension not found: {dimension_id}", "INVALID_DIMENSION")
        deleted = sketch.dimensions.pop(index)
        solver = self._solve_candidate(sketch)
        rebuild = self._commit_sketch_candidate(previous, document, part.id)
        return {
            "ok": True,
            "sketch_id": sketch.id,
            "deleted_dimension": dimension_to_dict(deleted),
            "solver_status": solver.status,
            "rebuild_status": "OK",
            "rebuild": rebuild,
        }

    @staticmethod
    def _entity_payload_mm(entity) -> dict[str, Any]:
        payload = {
            "id": entity.id,
            "type": entity.entity_type,
            "construction": bool(entity.construction),
        }
        if entity.entity_type == "LINE":
            payload.update(
                start_mm=[entity.x1 * 1000.0, entity.y1 * 1000.0],
                end_mm=[entity.x2 * 1000.0, entity.y2 * 1000.0],
            )
        elif entity.entity_type == "CIRCLE":
            payload.update(
                center_mm=[entity.cx * 1000.0, entity.cy * 1000.0],
                radius_mm=entity.radius * 1000.0,
                diameter_mm=entity.radius * 2000.0,
            )
        else:
            payload.update(
                center_mm=[entity.cx * 1000.0, entity.cy * 1000.0],
                radius_mm=entity.radius * 1000.0,
                start_deg=entity.start_angle * 180.0 / 3.141592653589793,
                end_deg=entity.end_angle * 180.0 / 3.141592653589793,
            )
        return payload

    def _get_sketch(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ..core.serialization import plane_reference_to_dict
        from ..sketch.constraints import constraint_to_dict
        from ..sketch.dimensions import dimension_to_dict
        from ..sketch.numeric import rectangle_parameters_by_id
        from ..sketch.solver import SketchSolver

        document = self._document()
        _part, sketch = self._sketch_location(document, str(arguments.get("sketch_id") or ""))
        result = SketchSolver().solve(deepcopy(sketch))
        dimensions = []
        for dimension in sketch.dimensions:
            item = dimension_to_dict(dimension)
            item["value_mm"] = dimension.value * 1000.0
            dimensions.append(item)
        rectangles = []
        for rectangle in sketch.rectangles:
            parameters = rectangle_parameters_by_id(sketch, rectangle.id)
            item = rectangle.to_dict()
            item["x_mm"] = parameters[0] * 1000.0 if parameters else None
            item["y_mm"] = parameters[1] * 1000.0 if parameters else None
            item["width_mm"] = parameters[2] * 1000.0 if parameters else None
            item["height_mm"] = parameters[3] * 1000.0 if parameters else None
            rectangles.append(item)
        return {
            "ok": True,
            "sketch_id": sketch.id,
            "name": sketch.name,
            "plane": plane_reference_to_dict(sketch.plane_reference),
            "entities": [self._entity_payload_mm(entity) for entity in sketch.entities],
            "dimensions": dimensions,
            "constraints": [constraint_to_dict(item) for item in sketch.constraints],
            "rectangles": rectangles,
            "solver_status": result.status,
            "solver_message": result.message,
            "feature_status": sketch.status,
        }

    def _get_history(self, arguments: dict[str, Any]) -> dict[str, Any]:
        document = self._document()
        part = self._part(document, arguments)
        return {
            "ok": True,
            "part_id": part.id,
            "part_name": part.name,
            "features": [
                {
                    "id": feature.id,
                    "name": feature.name,
                    "feature_type": feature.feature_type,
                    "status": feature.status,
                    "error_message": feature.error_message,
                    "dependencies": list(feature.dependencies),
                }
                for feature in part.features
            ],
        }

    def _get_edges(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Return semantic straight edges without exposing runtime mesh indices."""

        from ..blender.viewport.provenance import get_edge_candidates
        from ..core.serialization import edge_reference_to_dict

        document = self._document()
        part = self._part(document, arguments)
        result_object = next(
            (
                obj
                for obj in self._bpy.data.objects
                if obj.get("cad_generated") and obj.get("cad_part_id") == part.id
            ),
            None,
        )
        if result_object is None:
            return {"ok": True, "part_id": part.id, "edges": []}
        edges = []
        seen: set[str] = set()
        for candidate in get_edge_candidates(result_object).values():
            reference = candidate.semantic_reference
            if reference is None:
                continue
            key = json.dumps(edge_reference_to_dict(reference), sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "reference": edge_reference_to_dict(reference),
                    "start_mm": [candidate.start[index] * 1000.0 for index in range(3)],
                    "end_mm": [candidate.end[index] * 1000.0 for index in range(3)],
                    "length_mm": candidate.length * 1000.0,
                }
            )
        return {"ok": True, "part_id": part.id, "edges": edges}

    @staticmethod
    def _reference_key(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def _list_references(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """List persistent semantic references discoverable after a rebuild."""

        from ..blender.viewport.provenance import get_edge_candidates, get_face_candidates
        from ..core.serialization import edge_reference_to_dict, plane_reference_to_dict
        from ..sketch.plane import PlaneReference, get_runtime_evaluation

        document = self._document()
        part = self._part(document, arguments)
        feature_id = str(arguments.get("feature_id") or "")
        if feature_id:
            if part.get_feature(feature_id) is None:
                raise WorkerError(
                    f"Feature {feature_id} is not in Part Studio {part.id}.",
                    "REFERENCE_MISSING",
                )
        runtime = get_runtime_evaluation(part.id)
        planes: list[dict[str, Any]] = []
        faces: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        seen_planes: set[str] = set()
        seen_faces: set[str] = set()
        seen_edges: set[str] = set()

        if not feature_id:
            for datum in ("XY", "XZ", "YZ"):
                reference = {
                    "reference_type": "DATUM",
                    "datum_plane": datum,
                    "feature_id": None,
                    "role": None,
                    "source_entity_id": None,
                    "offset": 0.0,
                    "face_reference": None,
                }
                planes.append({"role": datum, "reference": reference})

        if runtime is not None:
            for (producer, role, source_entity_id), _resolved in sorted(
                getattr(runtime, "semantic_planes", {}).items(),
                key=lambda item: tuple(str(value or "") for value in item[0]),
            ):
                if feature_id and str(producer) != feature_id:
                    continue
                reference_type = "FEATURE_PLANE" if role == "END_PLANE" else "FACE"
                reference = plane_reference_to_dict(
                    PlaneReference(
                        reference_type=reference_type,
                        datum_plane=None,
                        feature_id=str(producer),
                        role=role,
                        source_entity_id=source_entity_id,
                    )
                )
                key = self._reference_key(reference)
                if key not in seen_planes:
                    seen_planes.add(key)
                    planes.append({"role": role, "reference": reference})
            for candidate in getattr(runtime, "derived_plane_candidates", {}).get(
                feature_id, ()
            ):
                reference = plane_reference_to_dict(candidate.to_reference())
                key = self._reference_key(reference)
                if key not in seen_planes:
                    seen_planes.add(key)
                    planes.append({"role": "DERIVED_PLANE", "reference": reference})

        result_object = next(
            (
                obj
                for obj in self._bpy.data.objects
                if obj.get("cad_generated") and obj.get("cad_part_id") == part.id
            ),
            None,
        )
        if result_object is not None:
            for candidate in get_face_candidates(result_object).values():
                reference = candidate.semantic_plane
                if reference is None:
                    continue
                producer = getattr(reference, "producer_feature_id", None) or getattr(
                    reference, "feature_id", None
                )
                if feature_id and str(producer) != feature_id:
                    continue
                payload = plane_reference_to_dict(reference)
                key = self._reference_key(payload)
                if key not in seen_planes:
                    seen_planes.add(key)
                    planes.append({"role": getattr(reference, "role", None), "reference": payload})
                face = candidate.semantic_face
                if face is not None:
                    face_payload = {"reference_type": "FACE", **face.to_dict()}
                    face_key = self._reference_key(face_payload)
                    if face_key not in seen_faces:
                        seen_faces.add(face_key)
                        faces.append({"role": face.role, "reference": face_payload})
            for candidate in get_edge_candidates(result_object).values():
                reference = candidate.semantic_reference
                if reference is None:
                    continue
                if feature_id and reference.producer_feature_id != feature_id:
                    continue
                payload = edge_reference_to_dict(reference)
                key = self._reference_key(payload)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append({"role": reference.role, "reference": payload})

        return {
            "ok": True,
            "part_id": part.id,
            "feature_id": feature_id or None,
            "planes": planes,
            "faces": faces,
            "edges": edges,
            "persistent_only": True,
        }

    def _inspect_geometry(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Return compact, read-only geometry health metrics in millimeters."""

        document = self._document()
        part = self._part(document, arguments)
        result_object = next(
            (
                obj
                for obj in self._bpy.data.objects
                if obj.get("cad_generated") and obj.get("cad_part_id") == part.id
            ),
            None,
        )
        if result_object is None or getattr(result_object, "data", None) is None:
            return {
                "ok": True,
                "part_id": part.id,
                "has_body": False,
                "connected_components": 0,
                "bbox_mm": None,
                "manifold": False,
                "volume_mm3": None,
            }
        mesh = result_object.data

        def point(vertex):
            value = vertex.co
            try:
                transformed = result_object.matrix_world @ value
                return tuple(float(transformed[index]) * 1000.0 for index in range(3))
            except (AttributeError, TypeError, ValueError):
                return tuple(float(value[index]) * 1000.0 for index in range(3))

        points = [point(vertex) for vertex in mesh.vertices]
        bbox = None
        if points:
            bbox = {
                "min_mm": [min(item[index] for item in points) for index in range(3)],
                "max_mm": [max(item[index] for item in points) for index in range(3)],
            }
        edge_faces: dict[tuple[int, int], int] = {}
        neighbors: dict[int, set[int]] = {}
        for face_index, polygon in enumerate(mesh.polygons):
            vertices = tuple(int(index) for index in polygon.vertices)
            for index, vertex_index in enumerate(vertices):
                edge = tuple(sorted((vertex_index, vertices[(index + 1) % len(vertices)])))
                edge_faces[edge] = edge_faces.get(edge, 0) + 1
                neighbors.setdefault(face_index, set())
                for other_index, other_polygon in enumerate(mesh.polygons):
                    if other_index == face_index:
                        continue
                    other_vertices = set(int(value) for value in other_polygon.vertices)
                    if edge[0] in other_vertices and edge[1] in other_vertices:
                        neighbors[face_index].add(other_index)
        visited: set[int] = set()
        components = 0
        for start in range(len(mesh.polygons)):
            if start in visited:
                continue
            components += 1
            stack = [start]
            visited.add(start)
            while stack:
                current = stack.pop()
                for neighbor in neighbors.get(current, ()):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        stack.append(neighbor)
        manifold = bool(mesh.polygons) and bool(edge_faces) and all(
            count == 2 for count in edge_faces.values()
        )
        volume = 0.0
        for polygon in mesh.polygons:
            vertices = tuple(int(index) for index in polygon.vertices)
            if len(vertices) < 3:
                continue
            origin = points[vertices[0]]
            for index in range(1, len(vertices) - 1):
                first = points[vertices[index]]
                second = points[vertices[index + 1]]
                cross = (
                    first[1] * second[2] - first[2] * second[1],
                    first[2] * second[0] - first[0] * second[2],
                    first[0] * second[1] - first[1] * second[0],
                )
                volume += sum(origin[item] * cross[item] for item in range(3)) / 6.0
        return {
            "ok": True,
            "part_id": part.id,
            "has_body": True,
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "polygons": len(mesh.polygons),
            "connected_components": components,
            "bbox_mm": bbox,
            "manifold": manifold,
            "volume_mm3": abs(volume),
            "units": "mm",
        }

    def _get_document(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        from ..core.serialization import document_to_dict

        return {"ok": True, "document": document_to_dict(self._document())}

    def _get_part_studio(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ..core.serialization import feature_to_dict

        document = self._document()
        part = self._part(document, arguments)
        return {
            "ok": True,
            "part": {
                "id": part.id,
                "name": part.name,
                "rollback_index": part.rollback_index,
                "features": [feature_to_dict(feature) for feature in part.features],
            },
        }

    def _get_feature(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ..core.serialization import feature_to_dict

        document = self._document()
        part, feature = self._feature_location(
            document, str(arguments.get("feature_id") or "")
        )
        return {
            "ok": True,
            "part_id": part.id,
            "feature": feature_to_dict(feature),
        }

    def _update_geometry(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ..core.serialization import entity_to_dict
        from ..sketch.entities import SketchArc, SketchCircle, SketchLine
        from ..sketch.numeric import (
            rectangle_definition_for,
            remove_rectangle_definitions_for_entities,
            set_arc,
            set_circle,
            set_rectangle,
        )

        document = self._document()
        previous = deepcopy(document)
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
            definition = rectangle_definition_for(sketch, entity_id=entity.id)
            if definition is not None:
                # A low-level side edit intentionally leaves the primitive
                # layer rather than silently keeping stale width/height
                # driving dimensions.  The ordinary line UUIDs survive.
                dimension_ids = {
                    item
                    for item in (definition.width_dimension_id, definition.height_dimension_id)
                    if item
                }
                sketch.dimensions = [
                    item for item in sketch.dimensions if item.id not in dimension_ids
                ]
                remove_rectangle_definitions_for_entities(
                    sketch, definition.entity_ids
                )
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
        solver = self._solve_candidate(sketch)
        rebuild = self._commit_sketch_candidate(previous, document, _part.id)
        return {
            "ok": True,
            "sketch_id": sketch.id,
            "entity": entity_to_dict(entity),
            "solver_status": solver.status,
            "rebuild": rebuild,
        }

    def _delete_geometry(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ..core.serialization import entity_to_dict
        from ..sketch.constraints import remove_constraints_for_entity
        from ..sketch.dimensions import remove_dimensions_for_entity
        from ..sketch.numeric import remove_rectangle_definitions_for_entities

        document = self._document()
        previous = deepcopy(document)
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
        removed_constraints = sum(
            remove_constraints_for_entity(sketch, entity.id) for entity in removed
        )
        removed_dimensions = sum(
            remove_dimensions_for_entity(sketch, entity.id) for entity in removed
        )
        removed_rectangles = remove_rectangle_definitions_for_entities(
            sketch, wanted
        )
        solver = self._solve_candidate(sketch)
        rebuild = self._commit_sketch_candidate(previous, document, _part.id)
        return {
            "ok": True,
            "sketch_id": sketch.id,
            "deleted": [entity_to_dict(item) for item in removed],
            "removed_constraints": removed_constraints,
            "removed_dimensions": removed_dimensions,
            "removed_rectangles": removed_rectangles,
            "solver_status": solver.status,
            "rebuild": rebuild,
        }

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
        from ..sketch.profile import ProfileDetector

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
        from ..sketch.profile import ProfileDetector

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
        result = self._profile({"sketch_id": sketch.id})
        result["rebuild"] = self._rebuild_payload(_part.id)
        return result

    def _restore_region(self, arguments: dict[str, Any]) -> dict[str, Any]:
        document = self._document()
        _part, sketch = self._sketch_location(document, str(arguments.get("sketch_id") or ""))
        region_id = str(arguments.get("region_id") or "")
        if region_id in sketch.deleted_regions:
            sketch.deleted_regions.remove(region_id)
        self._save_document(document)
        result = self._profile({"sketch_id": sketch.id})
        result["rebuild"] = self._rebuild_payload(_part.id)
        return result

    @staticmethod
    def _previous_body_feature(part, before_index: int):
        return next(
            (
                feature
                for feature in reversed(part.features[:before_index])
                if feature.feature_type in {"EXTRUDE", "REVOLVE", "TRANSFORM", "MIRROR", "CHAMFER", "FILLET"}
                and not feature.suppressed
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
        from ..blender.adapter import rebuild_part

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

    def _feature_result_response(
        self,
        part_id: str,
        feature,
        rebuild: dict[str, Any],
    ) -> dict[str, Any]:
        """Return a stable, direct feature result alongside legacy payloads."""

        from ..core.serialization import feature_to_dict

        document = self._document()
        part = document.get_part(part_id)
        current = part.get_feature(feature.id) if part is not None else feature
        status = next(
            (
                item["status"]
                for item in rebuild.get("features", ())
                if item.get("id") == feature.id
            ),
            getattr(current, "status", "NOT_EVALUATED"),
        )
        references = self._list_references(
            {"part_id": part_id, "feature_id": feature.id}
        )
        return {
            "part_id": part_id,
            "feature_id": feature.id,
            "feature_type": feature.feature_type,
            "status": status,
            "feature": feature_to_dict(current or feature),
            "references": {
                "planes": references.get("planes", []),
                "faces": references.get("faces", []),
                "edges": references.get("edges", []),
            },
            "rebuild": rebuild,
        }

    def _create_extrude(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ..core.serialization import feature_to_dict
        from ..features.extrude import ExtrudeFeature
        from ..sketch.profile import ProfileDetector
        from ..sketch.sketch import SketchFeature

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
        rebuild = self._rebuild_payload(part.id)
        return self._feature_result_response(part.id, feature, rebuild)

    def _axis_reference(self, axis_data: Any, part, sketch, axis_reverse: bool):
        from ..core.references import AxisReference
        from ..sketch.entities import SketchLine
        from ..sketch.sketch import SketchFeature

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
        from ..core.serialization import feature_to_dict
        from ..features.revolve import RevolveFeature
        from ..sketch.profile import ProfileDetector

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
        rebuild = self._rebuild_payload(part.id)
        return self._feature_result_response(part.id, feature, rebuild)

    @staticmethod
    def _mirror_plane_reference(value: Any):
        from ..sketch.plane import SketchPlaneReference

        if isinstance(value, str):
            plane = value.upper()
            if plane not in {"XY", "XZ", "YZ"}:
                raise WorkerError("mirror_plane must be XY, XZ, or YZ.")
            return SketchPlaneReference("DATUM", datum_plane=plane)
        if not isinstance(value, dict):
            raise WorkerError("mirror_plane must be a datum plane string or object.")
        reference_type = str(
            value.get("type") or value.get("reference_type") or "DATUM"
        ).upper()
        try:
            offset_mm = float(value.get("offset_mm", 0.0) or 0.0)
        except (TypeError, ValueError) as exc:
            raise WorkerError("mirror_plane.offset_mm must be numeric.") from exc
        if not isfinite(offset_mm):
            raise WorkerError("mirror_plane.offset_mm must be finite.")
        offset = offset_mm / 1000.0
        if reference_type == "DATUM":
            plane = str(value.get("plane") or value.get("datum_plane") or "YZ").upper()
            if plane not in {"XY", "XZ", "YZ"}:
                raise WorkerError("mirror_plane datum plane must be XY, XZ, or YZ.")
            return SketchPlaneReference("DATUM", datum_plane=plane, offset=offset)
        if reference_type == "FEATURE_PLANE":
            source_id = str(value.get("feature_id") or "")
            if not source_id:
                raise WorkerError("mirror_plane FEATURE_PLANE needs feature_id.")
            role = str(value.get("role") or "END_PLANE")
            return SketchPlaneReference(
                "FEATURE_PLANE",
                datum_plane=None,
                feature_id=source_id,
                role=role,
                offset=offset,
            )
        if reference_type == "FACE":
            source_id = str(value.get("feature_id") or "")
            role = str(value.get("role") or "")
            if not source_id or not role:
                raise WorkerError("mirror_plane FACE needs feature_id and role.")
            return SketchPlaneReference(
                "FACE",
                datum_plane=None,
                feature_id=source_id,
                role=role,
                source_entity_id=value.get("source_entity_id"),
                offset=offset,
            )
        raise WorkerError("mirror_plane type must be DATUM, FEATURE_PLANE, or FACE.")

    def _create_transform(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ..core.serialization import feature_to_dict
        from ..features.transform import TransformFeature

        document = self._document()
        part = self._part(document, arguments)
        previous = self._previous_body_feature(part, len(part.features))
        if previous is None:
            raise WorkerError("Transform requires an earlier body feature.")
        translation_mm = self._vector(arguments, "translation_mm")
        rotation_deg = self._vector(arguments, "rotation_deg")
        feature = TransformFeature(
            name=str(arguments.get("name") or part.next_feature_name("Transform")),
            translation=tuple(value / 1000.0 for value in translation_mm),
            rotation=tuple(radians(value) for value in rotation_deg),
            dependencies=[previous.id],
        )
        part.add_feature(feature)
        document.active_part_id = part.id
        self._save_document(document)
        rebuild = self._rebuild_payload(part.id)
        return self._feature_result_response(part.id, feature, rebuild)

    def _create_mirror(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ..core.serialization import feature_to_dict
        from ..features.extrude import ExtrudeFeature
        from ..features.mirror import MirrorFeature
        from ..features.revolve import RevolveFeature

        document = self._document()
        part = self._part(document, arguments)
        source_id = str(arguments.get("source_feature_id") or "")
        source = part.get_feature(source_id)
        if not isinstance(source, (ExtrudeFeature, RevolveFeature)) or source.operation != "ADD":
            raise WorkerError(
                "source_feature_id must reference an additive Extrude or Revolve feature."
            )
        previous = self._previous_body_feature(part, len(part.features))
        if previous is None:
            raise WorkerError("Mirror requires an earlier body feature.")
        plane = self._mirror_plane_reference(arguments.get("mirror_plane"))
        dependencies = [source.id]
        if previous.id not in dependencies:
            dependencies.append(previous.id)
        feature = MirrorFeature(
            name=str(arguments.get("name") or part.next_feature_name("Mirror")),
            source_feature_id=source.id,
            mirror_plane=plane,
            dependencies=dependencies,
        )
        part.add_feature(feature)
        document.active_part_id = part.id
        self._save_document(document)
        rebuild = self._rebuild_payload(part.id)
        return self._feature_result_response(part.id, feature, rebuild)

    def _edge_references(self, values: Any):
        from ..core.serialization import edge_reference_from_dict

        if not isinstance(values, list) or not values:
            raise WorkerError("edge_references must contain at least one persistent EdgeReference.")
        references = []
        for value in values:
            if not isinstance(value, dict):
                raise WorkerError("Each edge reference must be a JSON object.")
            if "mesh_edge_index" in value or "edge_index" in value:
                raise WorkerError(
                    "Persistent EdgeReference input cannot contain Blender edge indices."
                )
            try:
                reference = edge_reference_from_dict(value)
            except (TypeError, ValueError, KeyError) as exc:
                raise WorkerError(f"Invalid persistent EdgeReference: {exc}") from exc
            if reference.reference_type != "EDGE":
                raise WorkerError("edge_references may contain only persistent EDGE references.")
            references.append(reference)
        return references

    @staticmethod
    def _edge_feature_dependencies(part, references, before_index: int | None = None):
        previous = BlenderCadWorker._previous_body_feature(
            part, len(part.features) if before_index is None else before_index
        )
        dependencies = [previous.id] if previous is not None else []
        for reference in references:
            if reference.producer_feature_id not in dependencies:
                dependencies.append(reference.producer_feature_id)
        return dependencies

    def _create_edge_feature(self, arguments: dict[str, Any], kind: str) -> dict[str, Any]:
        from ..core.serialization import feature_to_dict
        from ..features.chamfer import ChamferFeature
        from ..features.fillet import FilletFeature

        document = self._document()
        part = self._part(document, arguments)
        references = self._edge_references(arguments.get("edge_references"))
        field = "distance_mm" if kind == "CHAMFER" else "radius_mm"
        amount = self._number(arguments, field) / 1000.0
        if amount <= 0.0:
            raise WorkerError(f"{field} must be greater than zero.")
        feature_class = ChamferFeature if kind == "CHAMFER" else FilletFeature
        parameter = {"distance": amount} if kind == "CHAMFER" else {"radius": amount}
        feature = feature_class(
            name=str(arguments.get("name") or part.next_feature_name(kind.title())),
            edge_references=references,
            dependencies=self._edge_feature_dependencies(part, references),
            **parameter,
        )
        part.add_feature(feature)
        document.active_part_id = part.id
        self._save_document(document)
        rebuild = self._rebuild_payload(part.id)
        return self._feature_result_response(part.id, feature, rebuild)

    def _create_chamfer(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._create_edge_feature(arguments, "CHAMFER")

    def _create_fillet(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._create_edge_feature(arguments, "FILLET")

    def _update_feature(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ..core.serialization import feature_to_dict
        from ..features.extrude import ExtrudeFeature
        from ..features.chamfer import ChamferFeature
        from ..features.fillet import FilletFeature
        from ..features.mirror import MirrorFeature
        from ..features.revolve import RevolveFeature
        from ..features.transform import TransformFeature
        from ..sketch.sketch import SketchFeature

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
        if isinstance(feature, SketchFeature):
            if "offset_mm" in arguments:
                try:
                    offset_mm = float(arguments["offset_mm"])
                except (TypeError, ValueError) as exc:
                    raise WorkerError("offset_mm must be numeric.") from exc
                if not isfinite(offset_mm):
                    raise WorkerError("offset_mm must be finite.")
                feature.set_plane_offset(offset_mm / 1000.0)
        elif isinstance(feature, ExtrudeFeature):
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
        elif isinstance(feature, TransformFeature):
            before_index = part.get_feature_index(feature.id)
            if "translation_mm" in arguments:
                feature.translation = tuple(
                    value / 1000.0 for value in self._vector(arguments, "translation_mm")
                )
            if "rotation_deg" in arguments:
                feature.rotation = tuple(
                    radians(value) for value in self._vector(arguments, "rotation_deg")
                )
            previous = self._previous_body_feature(part, before_index)
            feature.dependencies = [previous.id] if previous is not None else []
        elif isinstance(feature, MirrorFeature):
            before_index = part.get_feature_index(feature.id)
            if "source_feature_id" in arguments:
                source_id = str(arguments.get("source_feature_id") or "")
                source = part.get_feature(source_id)
                if not isinstance(source, (ExtrudeFeature, RevolveFeature)) or source.operation != "ADD":
                    raise WorkerError(
                        "source_feature_id must reference an additive Extrude or Revolve feature."
                    )
                if part.get_feature_index(source.id) >= before_index:
                    raise WorkerError("source_feature_id must reference an earlier feature.")
                feature.source_feature_id = source.id
            if "mirror_plane" in arguments:
                feature.mirror_plane = self._mirror_plane_reference(arguments["mirror_plane"])
            previous = self._previous_body_feature(part, before_index)
            dependencies = [feature.source_feature_id] if feature.source_feature_id else []
            if previous is not None and previous.id not in dependencies:
                dependencies.append(previous.id)
            feature.dependencies = dependencies
        elif isinstance(feature, (ChamferFeature, FilletFeature)):
            before_index = part.get_feature_index(feature.id)
            if "edge_references" in arguments:
                feature.edge_references = self._edge_references(arguments["edge_references"])
            if isinstance(feature, ChamferFeature) and "distance_mm" in arguments:
                feature.distance = self._number(arguments, "distance_mm") / 1000.0
            if isinstance(feature, FilletFeature) and "radius_mm" in arguments:
                feature.radius = self._number(arguments, "radius_mm") / 1000.0
            references = feature.edge_references
            feature.dependencies = self._edge_feature_dependencies(
                part, references, before_index=before_index
            )
        else:
            raise WorkerError(f"Unsupported feature type: {feature.feature_type}")
        document.active_part_id = part.id
        self._save_document(document)
        return {"part_id": part.id, "feature": feature_to_dict(feature), "rebuild": self._rebuild_payload(part.id)}

    def _delete_feature(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ..core.part import delete_feature
        from ..core.serialization import feature_to_dict

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

    def _validate_document(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        from ..blender.adapter import validate_cad_document

        diagnostics = validate_cad_document(self.scene)
        return {"valid": not diagnostics, "diagnostics": diagnostics}

    def _export_part(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ..blender.adapter import export_part

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
    parser.add_argument("--endpoint-file")
    parser.add_argument("--blend-file")
    parser.add_argument("--autosave")
    return parser


def _send(stream, message: dict[str, Any]) -> None:
    stream.write(json.dumps(message, ensure_ascii=False).encode("utf-8"))
    stream.write(b"\n")
    stream.flush()


class _VisibleSocketSession:
    """Service one MCP connection without blocking Blender's UI event loop."""

    interval = 0.01

    def __init__(self, worker: BlenderCadWorker, connection: socket.socket, token: str):
        self.worker = worker
        self.connection = connection
        self.token = token
        self._incoming = bytearray()
        self._outgoing = bytearray()
        self._shutdown_requested = False
        self._closed = False

    def start(self, register_timer: bool = True) -> None:
        self.connection.setblocking(True)
        self.connection.sendall(_message_bytes({"type": "hello", "token": self.token}))
        self.connection.setblocking(False)
        if register_timer:
            self.worker._bpy.app.timers.register(self.poll, first_interval=0.0)

    def poll(self):
        if self._closed:
            return None
        if not self._receive():
            self.close()
            return None
        self._flush()
        if self._shutdown_requested and not self._outgoing:
            self.close()
            return None
        return self.interval

    def _receive(self) -> bool:
        peer_closed = False
        while True:
            try:
                chunk = self.connection.recv(65536)
            except BlockingIOError:
                break
            except OSError:
                return False
            if not chunk:
                peer_closed = True
                break
            self._incoming.extend(chunk)
        while True:
            separator = self._incoming.find(b"\n")
            if separator < 0:
                break
            line = bytes(self._incoming[:separator])
            del self._incoming[: separator + 1]
            if line.strip():
                self._handle_line(line)
            if self._shutdown_requested:
                break
        return not peer_closed

    def _handle_line(self, line: bytes) -> None:
        request = None
        try:
            request = json.loads(line.decode("utf-8"))
            if not isinstance(request, dict):
                raise WorkerError("Worker message must be a JSON object.")
            if request.get("token") != self.token:
                raise WorkerError("Authentication failed.")
            method = request.get("method")
            if method == "shutdown":
                self._queue({"id": request.get("id"), "ok": True, "result": {}})
                self._shutdown_requested = True
                return
            if method != "tool":
                raise WorkerError(f"Unknown worker method: {method}")
            result = self.worker.handle(
                request.get("name"), request.get("arguments") or {}
            )
            self._queue({"id": request.get("id"), "ok": True, "result": result})
        except Exception as exc:
            code = getattr(exc, "code", "CAD_ERROR")
            error = {"code": code, "error_code": code, "message": str(exc)}
            details = getattr(exc, "details", None)
            if details is not None:
                error["details"] = details
            self._queue({
                "id": request.get("id") if isinstance(request, dict) else None,
                "ok": False,
                "error": error,
            })

    def _queue(self, message: dict[str, Any]) -> None:
        self._outgoing.extend(_message_bytes(message))

    def _flush(self) -> None:
        while self._outgoing:
            try:
                sent = self.connection.send(self._outgoing)
            except BlockingIOError:
                return
            except OSError:
                self.close()
                return
            if sent <= 0:
                self.close()
                return
            del self._outgoing[:sent]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.connection.close()
        except OSError:
            pass


class _VisibleSocketServer:
    """Keep one Blender window listening while MCP client processes reconnect."""

    interval = 0.01

    def __init__(
        self,
        worker: BlenderCadWorker,
        host: str,
        port: int,
        token: str,
        endpoint_file: str | None = None,
    ):
        self.worker = worker
        self.host = host
        self.port = port
        self.token = token
        self.endpoint_file = endpoint_path(endpoint_file)
        self.listener: socket.socket | None = None
        self.sessions: list[_VisibleSocketSession] = []
        self._closed = False

    @property
    def info(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "token": self.token,
            "endpoint_file": str(self.endpoint_file),
            "pid": os.getpid(),
        }

    def start(self) -> dict[str, Any]:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((self.host, self.port))
            listener.listen(8)
            listener.setblocking(False)
        except OSError:
            listener.close()
            raise
        self.listener = listener
        self.host, self.port = listener.getsockname()[:2]
        write_endpoint(
            {
                "host": self.host,
                "port": self.port,
                "token": self.token,
                "pid": os.getpid(),
            },
            self.endpoint_file,
        )
        self.worker._bpy.app.timers.register(self.poll, first_interval=0.0)
        return self.info

    def poll(self):
        if self._closed:
            return None
        self._accept_pending()
        for session in tuple(self.sessions):
            if session.poll() is None:
                self.sessions.remove(session)
        return self.interval

    def _accept_pending(self) -> None:
        if self.listener is None:
            return
        while True:
            try:
                connection, _address = self.listener.accept()
            except BlockingIOError:
                return
            except OSError:
                self.close()
                return
            session = _VisibleSocketSession(self.worker, connection, self.token)
            try:
                session.start(register_timer=False)
            except OSError:
                session.close()
                continue
            self.sessions.append(session)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.listener is not None:
            try:
                self.listener.close()
            except OSError:
                pass
            self.listener = None
        for session in self.sessions:
            session.close()
        self.sessions.clear()
        remove_endpoint(self.endpoint_file, token=self.token)


def start_embedded_service(
    host: str = "127.0.0.1",
    port: int = 9800,
    token: str | None = None,
    endpoint_file: str | None = None,
) -> dict[str, Any]:
    """Start the CAD MCP service inside the currently open Blender window."""

    global _EMBEDDED_SERVICE
    if _EMBEDDED_SERVICE is not None and not _EMBEDDED_SERVICE._closed:
        return _EMBEDDED_SERVICE.info
    resolved_port = int(port)
    resolved_endpoint = endpoint_path(endpoint_file)
    service = None
    try:
        with endpoint_lock(resolved_endpoint):
            existing = read_endpoint(resolved_endpoint)
            if existing and (
                _endpoint_is_current_process(existing)
                or endpoint_is_reachable(existing)
            ):
                raise RuntimeError(
                    "A CAD MCP Service is already running at "
                    f"{existing['host']}:{existing['port']}. Use the Blender "
                    "window that owns it, or stop that service before binding "
                    "this window; no second service was started."
                )
            if existing:
                # Only remove a stale endpoint after authentication data has
                # been validated by read_endpoint().
                remove_endpoint(resolved_endpoint, token=existing.get("token"))
            worker = BlenderCadWorker()
            service = _VisibleSocketServer(
                worker,
                host,
                resolved_port,
                token or secrets.token_urlsafe(32),
                str(resolved_endpoint),
            )
            info = service.start()
    except OSError as exc:
        if service is not None:
            service.close()
        if exc.errno == errno.EADDRINUSE:
            existing = read_endpoint(resolved_endpoint)
            if existing and (
                _endpoint_is_current_process(existing)
                or endpoint_is_reachable(existing)
            ):
                raise RuntimeError(
                    "A CAD MCP Service is already running at "
                    f"{existing['host']}:{existing['port']}. Use that Blender "
                    "window or stop it before starting this window; no second "
                    "service was started."
                ) from exc
            raise RuntimeError(
                f"Port {host}:{resolved_port} is already in use by another "
                "application. Choose a free port, and keep the same endpoint "
                "file for the MCP client."
            ) from exc
    except Exception:
        if service is not None:
            service.close()
        raise
    _EMBEDDED_SERVICE = service
    return info


def embedded_service_info() -> dict[str, Any] | None:
    """Return the current in-process service endpoint, if one is running."""

    if _EMBEDDED_SERVICE is None or _EMBEDDED_SERVICE._closed:
        return None
    return _EMBEDDED_SERVICE.info


def stop_embedded_service() -> None:
    """Stop the service hosted by this Blender process."""

    global _EMBEDDED_SERVICE
    if _EMBEDDED_SERVICE is not None:
        _EMBEDDED_SERVICE.close()
    _EMBEDDED_SERVICE = None


def _message_bytes(message: dict[str, Any]) -> bytes:
    return json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"


def _listen(host: str, port: int) -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind((host, port))
        listener.listen(8)
    except OSError:
        listener.close()
        raise
    return listener


def _run_blocking_service(worker: BlenderCadWorker, args) -> int:
    listener = _listen(args.host, args.port)
    endpoint_file = endpoint_path(args.endpoint_file)
    write_endpoint(
        {
            "host": args.host,
            "port": listener.getsockname()[1],
            "token": args.token,
            "pid": os.getpid(),
        },
        endpoint_file,
    )
    should_stop = False
    try:
        while not should_stop:
            connection, _address = listener.accept()
            reader = None
            writer = None
            try:
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
                            _send(
                                writer,
                                {"id": request.get("id"), "ok": True, "result": {}},
                            )
                            should_stop = True
                            break
                        if method != "tool":
                            raise WorkerError(f"Unknown worker method: {method}")
                        result = worker.handle(
                            request.get("name"), request.get("arguments") or {}
                        )
                        _send(
                            writer,
                            {"id": request.get("id"), "ok": True, "result": result},
                        )
                    except Exception as exc:
                        code = getattr(exc, "code", "CAD_ERROR")
                        error = {"code": code, "error_code": code, "message": str(exc)}
                        details = getattr(exc, "details", None)
                        if details is not None:
                            error["details"] = details
                        _send(
                            writer,
                            {
                                "id": request.get("id") if isinstance(request, dict) else None,
                                "ok": False,
                                "error": error,
                            },
                        )
            finally:
                for stream in (reader, writer):
                    if stream is not None:
                        stream.close()
                connection.close()
    finally:
        listener.close()
        remove_endpoint(endpoint_file, token=args.token)
    return 0


def _run_visible_service(worker: BlenderCadWorker, args) -> int:
    global _EMBEDDED_SERVICE
    service = _VisibleSocketServer(
        worker,
        args.host,
        args.port,
        args.token,
        args.endpoint_file,
    )
    try:
        service.start()
    except Exception:
        service.close()
        raise
    _EMBEDDED_SERVICE = service
    # The timer owns ``service`` after this function returns. Blender's normal
    # event loop remains active and the visible window can accept reconnects.
    return 0


def main() -> int:
    args = _parser().parse_args(_script_arguments())
    worker = BlenderCadWorker(args.blend_file, args.autosave)
    if worker._bpy.app.background:
        return _run_blocking_service(worker, args)
    return _run_visible_service(worker, args)


if __name__ == "__main__":
    raise SystemExit(main())
