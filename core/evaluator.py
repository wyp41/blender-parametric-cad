"""Sequential evaluation of Part history against a geometry backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..features.extrude import ExtrudeFeature
from ..geometry.backend import GeometryBackend
from ..sketch.plane import PlaneResolutionError, PlaneResolver, ResolvedPlane
from ..sketch.profile import ProfileDetector
from ..sketch.sketch import SketchFeature
from ..sketch.solver import SketchSolver
from .feature import Feature
from .part import Part


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
                feature.error_message = "Upstream feature evaluation failed."
                continue

            missing = [
                dependency
                for dependency in feature.dependencies
                if dependency not in context.evaluated_features
            ]
            if missing:
                message = "Required dependency is suppressed, invalid, or not evaluated."
                feature.error_message = message
                errors.append(EvaluationError(feature.id, feature.name, message))
                blocked = True
                continue

            if isinstance(feature, SketchFeature):
                blocked = not self._evaluate_sketch(feature, context, errors)
            elif isinstance(feature, ExtrudeFeature):
                blocked = not self._evaluate_extrude(feature, context, errors)
            else:
                self._record_error(
                    feature, f"Unsupported feature: {feature.feature_type}", errors
                )
                blocked = True

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
