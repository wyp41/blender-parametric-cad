"""Deterministic, Blender-independent lightweight Sketch solver."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from math import hypot

from ..core.references import SketchEntityReference
from .constraints import ConstraintError, validate_constraints
from .dimensions import DimensionError, apply_dimension, dimension_value, validate_dimensions
from .entities import SketchCircle, SketchLine
from .sketch import SketchFeature


SOLVED = "SOLVED"
CONFLICT = "CONFLICT"
INVALID_REFERENCE = "INVALID_REFERENCE"

_GEOMETRY_TOLERANCE = 1e-7
_DIRECTION_TOLERANCE = 1e-10


@dataclass
class SolverResult:
    success: bool
    message: str = ""
    status: str = ""

    def __post_init__(self) -> None:
        if not self.status:
            self.status = SOLVED if self.success else CONFLICT


def _entity(sketch: SketchFeature, reference: SketchEntityReference):
    if reference.sketch_id != sketch.id:
        raise ConstraintError(
            f"Reference belongs to Sketch {reference.sketch_id[:8]}, not {sketch.id[:8]}."
        )
    value = next((item for item in sketch.entities if item.id == reference.entity_id), None)
    if value is None:
        raise ConstraintError(f"Sketch entity reference {reference.entity_id[:8]} is missing.")
    return value


def _point(sketch: SketchFeature, reference: SketchEntityReference):
    entity = _entity(sketch, reference)
    if isinstance(entity, SketchLine):
        if reference.sub_element == "START":
            return (entity.x1, entity.y1), lambda value: _set_line_point(entity, "START", value)
        if reference.sub_element == "END":
            return (entity.x2, entity.y2), lambda value: _set_line_point(entity, "END", value)
    if isinstance(entity, SketchCircle) and reference.sub_element == "CENTER":
        return (entity.cx, entity.cy), lambda value: _set_circle_center(entity, value)
    raise ConstraintError(
        "Point constraints support Line.START, Line.END, and Circle.CENTER."
    )


def _set_line_point(entity: SketchLine, sub_element: str, value: tuple[float, float]) -> None:
    if sub_element == "START":
        entity.x1, entity.y1 = value
    else:
        entity.x2, entity.y2 = value


def _set_circle_center(entity: SketchCircle, value: tuple[float, float]) -> None:
    entity.cx, entity.cy = value


def _line_direction(entity: SketchLine) -> tuple[float, float, float]:
    dx, dy = entity.x2 - entity.x1, entity.y2 - entity.y1
    length = hypot(dx, dy)
    if length <= _DIRECTION_TOLERANCE:
        raise ConstraintError("A line constraint cannot use a zero-length line.", CONFLICT)
    return dx / length, dy / length, length


def _geometry_values(sketch: SketchFeature) -> list[float]:
    values: list[float] = []
    for entity in sketch.entities:
        if isinstance(entity, SketchLine):
            values.extend((entity.x1, entity.y1, entity.x2, entity.y2))
        elif isinstance(entity, SketchCircle):
            values.extend((entity.cx, entity.cy, entity.radius))
        else:
            values.extend(
                (
                    getattr(entity, "cx", 0.0),
                    getattr(entity, "cy", 0.0),
                    getattr(entity, "radius", 0.0),
                    getattr(entity, "start_angle", 0.0),
                    getattr(entity, "end_angle", 0.0),
                )
            )
    return values


def _copy_geometry(source: SketchFeature, target: SketchFeature) -> None:
    source_by_id = {entity.id: entity for entity in source.entities}
    for entity in target.entities:
        solved = source_by_id.get(entity.id)
        if solved is None:
            continue
        if isinstance(entity, SketchLine) and isinstance(solved, SketchLine):
            entity.x1, entity.y1 = solved.x1, solved.y1
            entity.x2, entity.y2 = solved.x2, solved.y2
        elif isinstance(entity, SketchCircle) and isinstance(solved, SketchCircle):
            entity.cx, entity.cy, entity.radius = solved.cx, solved.cy, solved.radius
        else:
            for name in ("cx", "cy", "radius", "start_angle", "end_angle"):
                if hasattr(entity, name) and hasattr(solved, name):
                    setattr(entity, name, getattr(solved, name))


class SketchSolver:
    """Project simple dimensions and constraints until their residuals vanish."""

    def __init__(self, max_iterations: int = 300, tolerance: float = _GEOMETRY_TOLERANCE):
        self.max_iterations = max_iterations
        self.tolerance = tolerance

    def solve(self, sketch: SketchFeature) -> SolverResult:
        try:
            # Validation updates M9B dimension diagnostics but never changes
            # geometry, so it is safe to perform before the transactional copy.
            validate_dimensions(sketch)
            validate_constraints(sketch)
        except (DimensionError, ConstraintError) as exc:
            status = getattr(exc, "status", None) or self._error_status(exc)
            return SolverResult(False, str(exc), status)

        working = deepcopy(sketch)
        try:
            self._validate_geometry(working)
            self._iterate(working)
            self._validate_geometry(working)
            residual = self._max_residual(working)
            if residual > self.tolerance:
                raise ConstraintError(
                    f"Sketch constraints cannot be satisfied (residual {residual:.3g} m).",
                    CONFLICT,
                )
        except (DimensionError, ConstraintError) as exc:
            status = getattr(exc, "status", None) or self._error_status(exc)
            return SolverResult(False, str(exc), status)

        _copy_geometry(working, sketch)
        for original, solved in zip(sketch.dimensions, working.dimensions):
            original.status, original.error_message = solved.status, solved.error_message
        return SolverResult(True, status=SOLVED)

    def _iterate(self, sketch: SketchFeature) -> None:
        if not sketch.dimensions and not any(item.enabled for item in sketch.constraints):
            return
        for _index in range(self.max_iterations):
            before = _geometry_values(sketch)
            for dimension in sketch.dimensions:
                if dimension.driving:
                    apply_dimension(sketch, dimension, dimension.value)
            for constraint in sketch.constraints:
                if constraint.enabled:
                    self._project_constraint(sketch, constraint)
            for dimension in sketch.dimensions:
                if dimension.driving:
                    apply_dimension(sketch, dimension, dimension.value)
            after = _geometry_values(sketch)
            if (
                before
                and max(abs(a - b) for a, b in zip(before, after)) <= self.tolerance
                and self._max_residual(sketch) <= self.tolerance
            ):
                break

    @staticmethod
    def _validate_geometry(sketch: SketchFeature) -> None:
        for entity in sketch.entities:
            if isinstance(entity, SketchLine):
                if hypot(entity.x2 - entity.x1, entity.y2 - entity.y1) <= _DIRECTION_TOLERANCE:
                    raise ConstraintError("Sketch contains a zero-length line.", CONFLICT)
            elif getattr(entity, "radius", 1.0) <= 0.0:
                label = "arc" if entity.entity_type == "ARC" else "circle"
                raise ConstraintError(f"Sketch contains an {label} with invalid radius.", CONFLICT)

    def _project_constraint(self, sketch: SketchFeature, constraint) -> None:
        kind = constraint.constraint_type
        refs = constraint.entity_refs
        if kind == "HORIZONTAL":
            line = _entity(sketch, refs[0])
            if not isinstance(line, SketchLine):
                raise ConstraintError("Horizontal only supports SketchLine.")
            y = (line.y1 + line.y2) * 0.5
            line.y1 = line.y2 = y
            return
        if kind == "VERTICAL":
            line = _entity(sketch, refs[0])
            if not isinstance(line, SketchLine):
                raise ConstraintError("Vertical only supports SketchLine.")
            x = (line.x1 + line.x2) * 0.5
            line.x1 = line.x2 = x
            return
        if kind == "COINCIDENT":
            first, set_first = _point(sketch, refs[0])
            second, set_second = _point(sketch, refs[1])
            midpoint = ((first[0] + second[0]) * 0.5, (first[1] + second[1]) * 0.5)
            set_first(midpoint)
            set_second(midpoint)
            return
        if kind in {"PARALLEL", "PERPENDICULAR"}:
            first = _entity(sketch, refs[0])
            second = _entity(sketch, refs[1])
            if not isinstance(first, SketchLine) or not isinstance(second, SketchLine):
                raise ConstraintError(f"{kind.title()} only supports SketchLine.")
            dx, dy, _ = _line_direction(first)
            if kind == "PERPENDICULAR":
                dx, dy = -dy, dx
            second_dx, second_dy, length = _line_direction(second)
            sign = 1.0 if dx * second_dx + dy * second_dy >= 0.0 else -1.0
            second.x2 = second.x1 + sign * dx * length
            second.y2 = second.y1 + sign * dy * length
            return
        if kind == "EQUAL":
            first = _entity(sketch, refs[0])
            second = _entity(sketch, refs[1])
            if isinstance(first, SketchLine) and isinstance(second, SketchLine):
                first_dx, first_dy, first_length = _line_direction(first)
                second_dx, second_dy, second_length = _line_direction(second)
                target = (first_length + second_length) * 0.5
                first.x2 = first.x1 + first_dx * target
                first.y2 = first.y1 + first_dy * target
                second.x2 = second.x1 + second_dx * target
                second.y2 = second.y1 + second_dy * target
                return
            if isinstance(first, SketchCircle) and isinstance(second, SketchCircle):
                radius = (first.radius + second.radius) * 0.5
                first.radius = second.radius = radius
                return
            raise ConstraintError("Equal supports Line + Line or Circle + Circle.")
        raise ConstraintError(f"Unsupported Sketch constraint: {kind!r}")

    def _max_residual(self, sketch: SketchFeature) -> float:
        residuals: list[float] = []
        for dimension in sketch.dimensions:
            if dimension.driving:
                residuals.append(abs(dimension_value(sketch, dimension) - dimension.value))
        for constraint in sketch.constraints:
            if constraint.enabled:
                residuals.append(self._constraint_residual(sketch, constraint))
        return max(residuals, default=0.0)

    @staticmethod
    def _constraint_residual(sketch: SketchFeature, constraint) -> float:
        refs = constraint.entity_refs
        kind = constraint.constraint_type
        if kind == "HORIZONTAL":
            line = _entity(sketch, refs[0])
            return abs(line.y2 - line.y1)
        if kind == "VERTICAL":
            line = _entity(sketch, refs[0])
            return abs(line.x2 - line.x1)
        if kind == "COINCIDENT":
            first, _ = _point(sketch, refs[0])
            second, _ = _point(sketch, refs[1])
            return hypot(first[0] - second[0], first[1] - second[1])
        first = _entity(sketch, refs[0])
        second = _entity(sketch, refs[1])
        if kind in {"PARALLEL", "PERPENDICULAR"}:
            first_dx, first_dy, _ = _line_direction(first)
            second_dx, second_dy, _ = _line_direction(second)
            dot = first_dx * second_dx + first_dy * second_dy
            cross = first_dx * second_dy - first_dy * second_dx
            return abs(cross if kind == "PARALLEL" else dot)
        if kind == "EQUAL":
            if isinstance(first, SketchLine) and isinstance(second, SketchLine):
                return abs(
                    hypot(first.x2 - first.x1, first.y2 - first.y1)
                    - hypot(second.x2 - second.x1, second.y2 - second.y1)
                )
            return abs(first.radius - second.radius)
        return 0.0

    @staticmethod
    def _error_status(error: Exception) -> str:
        message = str(error).lower()
        if any(token in message for token in ("reference", "missing", "supports", "requires")):
            return INVALID_REFERENCE
        return CONFLICT
