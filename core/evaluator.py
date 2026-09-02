"""Sequential evaluation of Part history against a geometry backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite, sqrt, tau
from typing import Any

from ..features.extrude import ExtrudeFeature
from ..features.revolve import RevolveFeature
from ..geometry.backend import GeometryBackend
from ..sketch.entities import SketchLine
from ..sketch.plane import PlaneResolutionError, PlaneResolver, ResolvedPlane
from ..sketch.profile import ProfileDetector
from ..sketch.sketch import SketchFeature, sketch_to_world
from ..sketch.solver import SketchSolver
from .feature import Feature
from .part import Part
from .references import TopoReference


@dataclass(frozen=True)
class EvaluationError:
    feature_id: str
    feature_name: str
    message: str


@dataclass
class EvaluationContext:
    """Resolved, non-persistent information produced during one full rebuild."""

    part: Part
    current_body: Any = None
    resolved_planes: dict[str, ResolvedPlane] = field(default_factory=dict)
    evaluated_features: dict[str, Feature] = field(default_factory=dict)
    face_provenance: dict[int, TopoReference] = field(default_factory=dict)


@dataclass
class EvaluationResult:
    success: bool
    body: Any = None
    errors: list[EvaluationError] = field(default_factory=list)
    context: EvaluationContext | None = None


class PartEvaluator:
    """Recompute disposable geometry from ordered persistent feature history."""

    def __init__(self, geometry_backend: GeometryBackend):
        self.geometry_backend = geometry_backend
        self.solver = SketchSolver()
        self.profile_detector = ProfileDetector()
        self.plane_resolver = PlaneResolver()

    def evaluate(self, part: Part) -> EvaluationResult:
        errors: list[EvaluationError] = []
        context = EvaluationContext(part)
        blocked = False
        blocked_by: Feature | None = None

        for feature in part.features:
            feature.status = "NOT_EVALUATED"
            feature.error_message = ""

        limit = len(part.features) - 1
        if part.rollback_index is not None:
            limit = min(part.rollback_index, limit)

        for index, feature in enumerate(part.features):
            if index > limit:
                feature.error_message = "Feature is after the rollback point."
                continue
            if feature.suppressed:
                feature.status = "SUPPRESSED"
                continue
            if blocked:
                name = blocked_by.name if blocked_by is not None else "an upstream feature"
                message = (
                    f"Blocked by failed feature {name}: {blocked_by.error_message}"
                    if blocked_by
                    else "Blocked by an upstream feature failure."
                )
                feature.status = "BLOCKED"
                feature.error_message = message
                errors.append(EvaluationError(feature.id, feature.name, message))
                continue

            missing = [
                dependency
                for dependency in feature.dependencies
                if dependency not in context.evaluated_features
            ]
            if missing:
                message = "Required dependency is suppressed, invalid, or not evaluated."
                feature.status = "ERROR"
                feature.error_message = message
                errors.append(EvaluationError(feature.id, feature.name, message))
                blocked = True
                blocked_by = feature
                continue

            previous_body = context.current_body
            previous_provenance = dict(context.face_provenance)
            if isinstance(feature, SketchFeature):
                blocked = not self._evaluate_sketch(feature, context, errors)
            elif isinstance(feature, ExtrudeFeature):
                blocked = not self._evaluate_extrude(feature, context, errors)
            elif isinstance(feature, RevolveFeature):
                blocked = not self._evaluate_revolve(feature, context, errors)
            else:
                self._record_error(
                    feature, f"Unsupported feature: {feature.feature_type}", errors
                )
                blocked = True
            if blocked:
                # Feature evaluation is transactional: a backend that created
                # a temporary body before raising cannot leak that partial body
                # into the result returned to the viewport.
                context.current_body = previous_body
                context.face_provenance = previous_provenance
                blocked_by = feature

        return EvaluationResult(not errors, context.current_body, errors, context)

    def _evaluate_sketch(
        self,
        feature: SketchFeature,
        context: EvaluationContext,
        errors: list[EvaluationError],
    ) -> bool:
        try:
            plane = self.plane_resolver.resolve(feature.plane_reference, context)
        except PlaneResolutionError as exc:
            self._record_error(feature, str(exc), errors)
            return False
        feature.apply_resolved_plane(plane)
        solved = self.solver.solve(feature)
        if not solved.success:
            self._record_error(feature, solved.message, errors)
            return False
        context.resolved_planes[feature.id] = plane
        self._mark_evaluated(feature, context)
        return True

    def _evaluate_extrude(
        self,
        feature: ExtrudeFeature,
        context: EvaluationContext,
        errors: list[EvaluationError],
    ) -> bool:
        source = context.evaluated_features.get(feature.sketch_id)
        if not isinstance(source, SketchFeature):
            self._record_error(feature, "Source sketch is missing or invalid.", errors)
            return False
        detected = self.profile_detector.detect(source)
        if not detected.success or detected.profile is None:
            self._record_error(feature, detected.message, errors)
            return False

        operation = "REMOVE" if feature.operation == "CUT" else feature.operation
        if operation == "NEW":
            if feature.depth_mode != "BLIND":
                self._record_error(feature, "NEW extrusion requires BLIND depth.", errors)
                return False
            if feature.distance <= 0.0:
                self._record_error(
                    feature, "Extrusion distance must be greater than zero.", errors
                )
                return False
            if context.current_body is not None:
                self._record_error(
                    feature,
                    "Multiple bodies are not supported yet. Use Add or Remove.",
                    errors,
                )
                return False
            try:
                context.current_body = self.geometry_backend.create_extrusion(
                    source,
                    detected.profile,
                    feature.distance,
                    feature.direction,
                )
                self.geometry_backend.register_extrude_provenance(
                    context.current_body, feature.id, detected.profile
                )
                context.face_provenance = self._supported_face_provenance(
                    self.geometry_backend.face_provenance(context.current_body),
                    source,
                )
            except Exception as exc:
                self._record_error(feature, str(exc), errors)
                return False
        elif operation in {"ADD", "REMOVE"}:
            if operation == "ADD" and feature.depth_mode != "BLIND":
                self._record_error(feature, "ADD extrusion requires BLIND depth.", errors)
                return False
            if context.current_body is None:
                self._record_error(feature, f"{operation} has no input body.", errors)
                return False
            if feature.depth_mode == "BLIND" and feature.distance <= 0.0:
                self._record_error(
                    feature, "Extrusion distance must be greater than zero.", errors
                )
                return False
            if feature.depth_mode not in {"BLIND", "THROUGH_ALL"}:
                self._record_error(feature, "Unsupported extrusion depth mode.", errors)
                return False
            try:
                tool = (
                    self.geometry_backend.create_blind_extrusion_tool(
                        source,
                        detected.profile,
                        feature.distance,
                        feature.direction,
                    )
                    if operation == "REMOVE" and feature.depth_mode == "BLIND"
                    else self.geometry_backend.create_extrusion(
                        source,
                        detected.profile,
                        feature.distance,
                        feature.direction,
                    )
                    if feature.depth_mode == "BLIND"
                    else self.geometry_backend.create_extrusion_tool(
                        source,
                        detected.profile,
                        context.current_body,
                        feature.direction,
                    )
                )
                result_body = (
                    self.geometry_backend.boolean_union(context.current_body, tool)
                    if operation == "ADD"
                    else self.geometry_backend.boolean_difference(context.current_body, tool)
                )
                if result_body is None:
                    raise ValueError(f"Boolean {operation.title()} produced no result.")
                context.current_body = result_body
                context.face_provenance = {}
            except Exception as exc:
                self._record_error(feature, str(exc), errors)
                return False
        else:
            self._record_error(
                feature, f"Unsupported extrusion operation: {feature.operation}", errors
            )
            return False

        self._mark_evaluated(feature, context)
        return True

    def _evaluate_revolve(
        self,
        feature: RevolveFeature,
        context: EvaluationContext,
        errors: list[EvaluationError],
    ) -> bool:
        source = context.evaluated_features.get(feature.sketch_id)
        if not isinstance(source, SketchFeature):
            self._record_error(feature, "Source sketch is missing or invalid.", errors)
            return False
        if feature.operation not in {"NEW", "ADD", "REMOVE"}:
            self._record_error(
                feature, f"Unsupported revolve operation: {feature.operation}", errors
            )
            return False
        if not isfinite(feature.angle) or feature.angle <= 0.0 or feature.angle > tau + 1e-9:
            self._record_error(
                feature, "Revolve angle must be greater than zero and no more than 360 degrees.", errors
            )
            return False

        axis = self._resolve_axis(feature.axis_reference, context, errors, feature)
        if axis is None:
            return False
        axis_origin, axis_direction = axis
        profile_entities = [
            entity
            for entity in source.entities
            if not entity.construction
            and not (
                feature.axis_reference.reference_type == "SKETCH_LINE"
                and feature.axis_reference.sketch_id == source.id
                and entity.id == feature.axis_reference.entity_id
            )
        ]
        detected = self.profile_detector.detect_entities(
            profile_entities, source.deleted_regions
        )
        if not detected.success or detected.profile is None:
            self._record_error(feature, detected.message, errors)
            return False

        if feature.operation == "NEW":
            if context.current_body is not None:
                self._record_error(
                    feature,
                    "Multiple bodies are not supported yet. Use Add or Remove.",
                    errors,
                )
        elif context.current_body is None:
            self._record_error(feature, f"{feature.operation} has no input body.", errors)
        if feature.status == "ERROR":
            return False

        try:
            tool = self.geometry_backend.revolve_profile(
                source,
                detected.profile,
                axis_origin,
                axis_direction,
                feature.angle,
            )
            if feature.operation == "NEW":
                context.current_body = tool
            elif feature.operation == "ADD":
                context.current_body = self.geometry_backend.boolean_union(
                    context.current_body, tool
                )
            else:
                context.current_body = self.geometry_backend.boolean_difference(
                    context.current_body, tool
                )
            if context.current_body is None:
                raise ValueError(f"Boolean {feature.operation.title()} produced no result.")
            context.face_provenance = {}
        except Exception as exc:
            self._record_error(feature, str(exc), errors)
            return False

        self._mark_evaluated(feature, context)
        return True

    @staticmethod
    def _resolve_axis(reference, context, errors, feature):
        datum_axes = {
            "X": (1.0, 0.0, 0.0),
            "Y": (0.0, 1.0, 0.0),
            "Z": (0.0, 0.0, 1.0),
        }
        if reference.reference_type == "DATUM_AXIS":
            if reference.axis not in datum_axes:
                PartEvaluator._record_error(
                    feature, f"Unsupported datum axis: {reference.axis}", errors
                )
                return None
            direction = -1.0 if reference.direction < 0 else 1.0
            return (0.0, 0.0, 0.0), tuple(
                direction * value for value in datum_axes[reference.axis]
            )
        if reference.reference_type != "SKETCH_LINE":
            PartEvaluator._record_error(feature, "Axis is not resolved.", errors)
            return None
        sketch = context.evaluated_features.get(reference.sketch_id)
        if not isinstance(sketch, SketchFeature):
            PartEvaluator._record_error(
                feature, "Axis source Sketch is missing or invalid.", errors
            )
            return None
        line = next(
            (
                entity
                for entity in sketch.entities
                if isinstance(entity, SketchLine) and entity.id == reference.entity_id
            ),
            None,
        )
        if line is None:
            PartEvaluator._record_error(
                feature, "Referenced SketchLine axis is unavailable.", errors
            )
            return None
        start = sketch_to_world(sketch, line.x1, line.y1)
        end = sketch_to_world(sketch, line.x2, line.y2)
        vector = tuple(end[index] - start[index] for index in range(3))
        length = sqrt(sum(value * value for value in vector))
        if length <= 1e-12:
            PartEvaluator._record_error(
                feature, "Referenced SketchLine axis has zero length.", errors
            )
            return None
        direction = -1.0 if reference.direction < 0 else 1.0
        return start, tuple(direction * value / length for value in vector)

    @staticmethod
    def _supported_face_provenance(provenance, sketch: SketchFeature):
        """Expose only references whose plane resolver can currently follow.

        Start/end faces remain selectable for every simple Extrude profile.
        Side-face supports are intentionally limited to source SketchLines;
        arc side planes are visible geometry but do not yet have a semantic
        plane resolver.
        """

        line_ids = {
            entity.id for entity in sketch.entities if isinstance(entity, SketchLine)
        }
        return {
            polygon_index: reference
            for polygon_index, reference in provenance.items()
            if reference.role != "SIDE_FACE"
            or reference.source_entity_id in line_ids
        }

    @staticmethod
    def _mark_evaluated(feature: Feature, context: EvaluationContext) -> None:
        feature.status = "OK"
        feature.error_message = ""
        context.evaluated_features[feature.id] = feature

    @staticmethod
    def _record_error(
        feature: Feature, message: str, errors: list[EvaluationError]
    ) -> None:
        feature.status = "ERROR"
        feature.error_message = message
        errors.append(EvaluationError(feature.id, feature.name, message))
