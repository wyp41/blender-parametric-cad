"""Blender-independent driving dimensions for Sketch geometry.

M9 deliberately provides direct dimension edits, not a general constraint
solver.  A dimension stores semantic Sketch UUIDs and changes only the
geometry needed for that one measurement.  All coordinates remain in meters;
the Blender UI converts to and from millimeters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot, isfinite, sqrt
from typing import Any, Callable, TYPE_CHECKING

from ..core.feature import new_uuid
from ..core.references import SketchEntityReference
from .entities import SketchArc, SketchCircle, SketchEntity, SketchLine

if TYPE_CHECKING:
    from .sketch import SketchFeature


LENGTH = "LENGTH"
HORIZONTAL_DISTANCE = "HORIZONTAL_DISTANCE"
VERTICAL_DISTANCE = "VERTICAL_DISTANCE"
DISTANCE = "DISTANCE"
RADIUS = "RADIUS"
DIAMETER = "DIAMETER"

DIMENSION_TYPES = (
    LENGTH,
    HORIZONTAL_DISTANCE,
    VERTICAL_DISTANCE,
    DISTANCE,
    RADIUS,
    DIAMETER,
)
POINT_SUB_ELEMENTS = frozenset({"START", "END", "CENTER"})
_EPSILON = 1e-12


class DimensionError(ValueError):
    """A dimension is invalid, unsupported, missing, or conflicts."""


@dataclass
class SketchDimension:
    """Persistent Sketch dimension metadata.

    ``entity_refs`` contains only :class:`SketchEntityReference` objects.  No
    Blender object, curve point, mesh index, or runtime selection candidate is
    serialized through this class.
    """

    id: str = field(default_factory=new_uuid)
    dimension_type: str = DISTANCE
    entity_refs: list[SketchEntityReference] = field(default_factory=list)
    value: float = 0.0
    driving: bool = True
    label_position: tuple[float, float] | None = None
    status: str = "OK"
    error_message: str = ""

    def __post_init__(self) -> None:
        self.id = str(self.id or new_uuid())
        self.dimension_type = str(self.dimension_type).upper()
        if self.dimension_type not in DIMENSION_TYPES:
            raise ValueError(f"Unsupported Sketch dimension type: {self.dimension_type!r}")
        self.entity_refs = [
            ref if isinstance(ref, SketchEntityReference)
            else SketchEntityReference.from_dict(ref)
            for ref in self.entity_refs
        ]
        self.value = float(self.value)
        if self.label_position is not None:
            if len(self.label_position) != 2:
                raise ValueError("Dimension label position must contain two values.")
            self.label_position = (
                float(self.label_position[0]),
                float(self.label_position[1]),
            )


def dimension_to_dict(dimension: SketchDimension) -> dict[str, Any]:
    """Serialize a dimension without runtime selection data."""

    return {
        "id": dimension.id,
        "dimension_type": dimension.dimension_type,
        "entity_refs": [reference.to_dict() for reference in dimension.entity_refs],
        "value": dimension.value,
        "driving": bool(dimension.driving),
        "label_position": list(dimension.label_position)
        if dimension.label_position is not None
        else None,
        "status": dimension.status,
        "error_message": dimension.error_message,
    }


def dimension_from_dict(data: dict[str, Any]) -> SketchDimension:
    if not isinstance(data, dict):
        raise ValueError("Sketch dimension must be a JSON object.")
    label = data.get("label_position")
    return SketchDimension(
        id=str(data.get("id") or new_uuid()),
        dimension_type=str(data.get("dimension_type", DISTANCE)),
        entity_refs=[SketchEntityReference.from_dict(item) for item in data.get("entity_refs", ())],
        value=float(data.get("value", 0.0)),
        driving=bool(data.get("driving", True)),
        label_position=tuple(float(item) for item in label[:2]) if label else None,
        status=str(data.get("status", "OK")),
        error_message=str(data.get("error_message", "")),
    )


def _entity_for_reference(
    sketch: "SketchFeature", reference: SketchEntityReference
) -> SketchEntity:
    if reference.sketch_id != sketch.id:
        raise DimensionError(
            f"Reference belongs to Sketch {reference.sketch_id[:8]}, not {sketch.id[:8]}."
        )
    entity = next((item for item in sketch.entities if item.id == reference.entity_id), None)
    if entity is None:
        raise DimensionError(
            f"Sketch entity reference {reference.entity_id[:8]} is missing."
        )
    return entity


def _sub_element(reference: SketchEntityReference, default: str = "ENTITY") -> str:
    return reference.sub_element or default


def _point_for_reference(
    sketch: "SketchFeature", reference: SketchEntityReference
) -> tuple[tuple[float, float], Callable[[tuple[float, float]], None]]:
    """Return a local point and a setter for supported point sub-elements."""

    entity = _entity_for_reference(sketch, reference)
    sub_element = _sub_element(reference, "")
    if isinstance(entity, SketchLine):
        if sub_element == "START":
            return (entity.x1, entity.y1), lambda point: _set_line_point(entity, "START", point)
        if sub_element == "END":
            return (entity.x2, entity.y2), lambda point: _set_line_point(entity, "END", point)
    elif isinstance(entity, SketchCircle) and sub_element == "CENTER":
        return (entity.cx, entity.cy), lambda point: _set_circle_center(entity, point)
    elif isinstance(entity, SketchArc):
        # Arc endpoints are useful for picking and display, but changing an
        # arc endpoint also changes its angle.  Keep that edit explicit until
        # a later constraint milestone defines its semantics.
        if sub_element == "CENTER":
            return (entity.cx, entity.cy), lambda point: _set_arc_center(entity, point)
        if sub_element in {"START", "END"}:
            angle = entity.start_angle if sub_element == "START" else entity.end_angle
            return entity.point(angle), lambda point: _set_arc_endpoint(
                entity, sub_element, point
            )
    raise DimensionError(
        f"{entity.entity_type} does not expose point sub-element {sub_element!r}."
    )


def _set_line_point(entity: SketchLine, sub_element: str, point: tuple[float, float]) -> None:
    if sub_element == "START":
        entity.x1, entity.y1 = point
    else:
        entity.x2, entity.y2 = point


def _set_circle_center(entity: SketchCircle, point: tuple[float, float]) -> None:
    entity.cx, entity.cy = point


def _set_arc_center(entity: SketchArc, point: tuple[float, float]) -> None:
    entity.cx, entity.cy = point


def _set_arc_endpoint(entity: SketchArc, sub_element: str, point: tuple[float, float]) -> None:
    from math import atan2

    angle = atan2(point[1] - entity.cy, point[0] - entity.cx)
    if sub_element == "START":
        entity.start_angle = angle
    else:
        entity.end_angle = angle


def _scalar_entity(
    sketch: "SketchFeature", reference: SketchEntityReference, expected_type: type
) -> SketchEntity:
    entity = _entity_for_reference(sketch, reference)
    if not isinstance(entity, expected_type):
        raise DimensionError(
            f"{reference.entity_id[:8]} is {entity.entity_type}; expected {expected_type.__name__}."
        )
    if _sub_element(reference) not in {"ENTITY", ""}:
        raise DimensionError("A scalar dimension must reference the whole entity.")
    return entity


def _require_positive_value(dimension: SketchDimension) -> None:
    if not isfinite(dimension.value):
        raise DimensionError("Dimension value must be finite.")
    if dimension.dimension_type in {LENGTH, DISTANCE, RADIUS, DIAMETER} and dimension.value <= 0.0:
        raise DimensionError("Length, distance, radius, and diameter must be greater than zero.")


def validate_dimension(sketch: "SketchFeature", dimension: SketchDimension) -> None:
    """Validate references and the supported direct-edit shape of a dimension."""

    if dimension.dimension_type not in DIMENSION_TYPES:
        raise DimensionError(f"Unsupported Sketch dimension type: {dimension.dimension_type!r}")
    _require_positive_value(dimension)
    refs = dimension.entity_refs
    kind = dimension.dimension_type
    if kind == LENGTH:
        if len(refs) != 1:
            raise DimensionError("Length requires one SketchLine reference.")
        _scalar_entity(sketch, refs[0], SketchLine)
    elif kind in {RADIUS, DIAMETER}:
        if len(refs) != 1:
            raise DimensionError(f"{kind.title()} requires one SketchCircle reference.")
        _scalar_entity(sketch, refs[0], SketchCircle)
    else:
        if len(refs) != 2:
            raise DimensionError(f"{kind.replace('_', ' ').title()} requires two point references.")
        for reference in refs:
            if reference.sub_element not in POINT_SUB_ELEMENTS:
                raise DimensionError(
                    "Point distance dimensions require START, END, or CENTER references."
                )
            _point_for_reference(sketch, reference)
        if refs[0] == refs[1]:
            raise DimensionError("A point distance dimension needs two different references.")


def dimension_value(sketch: "SketchFeature", dimension: SketchDimension) -> float:
    """Measure a dimension from the current Sketch geometry in meters."""

    validate_dimension(sketch, dimension)
    kind = dimension.dimension_type
    refs = dimension.entity_refs
    if kind == LENGTH:
        entity = _scalar_entity(sketch, refs[0], SketchLine)
        return hypot(entity.x2 - entity.x1, entity.y2 - entity.y1)
    if kind in {RADIUS, DIAMETER}:
        entity = _scalar_entity(sketch, refs[0], SketchCircle)
        return entity.radius if kind == RADIUS else entity.radius * 2.0
    first, _ = _point_for_reference(sketch, refs[0])
    second, _ = _point_for_reference(sketch, refs[1])
    dx, dy = second[0] - first[0], second[1] - first[1]
    if kind == HORIZONTAL_DISTANCE:
        return dx
    if kind == VERTICAL_DISTANCE:
        return dy
    return hypot(dx, dy)


def apply_dimension(sketch: "SketchFeature", dimension: SketchDimension, value: float) -> None:
    """Apply one driving dimension while preserving all entity UUIDs."""

    original_value = dimension.value
    try:
        _apply_dimension_value(sketch, dimension, value)
    except Exception:
        dimension.value = original_value
        raise


def _apply_dimension_value(
    sketch: "SketchFeature", dimension: SketchDimension, value: float
) -> None:
    """Implementation split out so a failed edit is atomic for metadata."""

    if not dimension.driving:
        raise DimensionError("Reference dimensions are read-only.")
    value = float(value)
    if not isfinite(value):
        raise DimensionError("Dimension value must be finite.")
    dimension.value = value
    _require_positive_value(dimension)
    validate_dimension(sketch, dimension)
    kind = dimension.dimension_type
    refs = dimension.entity_refs
    if kind == LENGTH:
        entity = _scalar_entity(sketch, refs[0], SketchLine)
        dx, dy = entity.x2 - entity.x1, entity.y2 - entity.y1
        length = hypot(dx, dy)
        if length <= _EPSILON:
            raise DimensionError("Cannot edit the length of a zero-length line.")
        entity.x2 = entity.x1 + dx / length * value
        entity.y2 = entity.y1 + dy / length * value
        return
    if kind in {RADIUS, DIAMETER}:
        entity = _scalar_entity(sketch, refs[0], SketchCircle)
        entity.radius = value if kind == RADIUS else value / 2.0
        return
    first, _ = _point_for_reference(sketch, refs[0])
    _, set_second = _point_for_reference(sketch, refs[1])
    if kind == HORIZONTAL_DISTANCE:
        set_second((first[0] + value, _point_for_reference(sketch, refs[1])[0][1]))
    elif kind == VERTICAL_DISTANCE:
        set_second((_point_for_reference(sketch, refs[1])[0][0], first[1] + value))
    else:
        second, _ = _point_for_reference(sketch, refs[1])
        dx, dy = second[0] - first[0], second[1] - first[1]
        length = hypot(dx, dy)
        if length <= _EPSILON:
            raise DimensionError("Cannot edit a distance with no current direction.")
        set_second((first[0] + dx / length * value, first[1] + dy / length * value))


def _reference_key(reference: SketchEntityReference) -> tuple[str, str, str | None]:
    return (reference.sketch_id, reference.entity_id, reference.sub_element)


def _dimension_conflict_key(dimension: SketchDimension) -> tuple[Any, ...]:
    refs = tuple(_reference_key(reference) for reference in dimension.entity_refs)
    if dimension.dimension_type == LENGTH:
        return ("SCALAR", LENGTH, refs[0] if refs else None)
    if dimension.dimension_type in {RADIUS, DIAMETER}:
        return ("SCALAR", "RADIAL", refs[0] if refs else None)
    return ("PAIR", dimension.dimension_type, refs)


def validate_dimension_conflicts(
    sketch: "SketchFeature", candidate: SketchDimension
) -> None:
    """Reject duplicate driving dimensions instead of silently over-constraining."""

    validate_dimension(sketch, candidate)
    candidate_key = _dimension_conflict_key(candidate)
    for existing in sketch.dimensions:
        if existing.id == candidate.id:
            continue
        if _dimension_conflict_key(existing) == candidate_key:
            raise DimensionError(
                f"Dimension conflicts with existing {existing.dimension_type.title()} dimension."
            )


def remove_dimensions_for_entity(sketch: "SketchFeature", entity_id: str) -> int:
    """Cascade-remove dimensions that would otherwise contain stale UUIDs."""

    before = len(sketch.dimensions)
    sketch.dimensions = [
        dimension
        for dimension in sketch.dimensions
        if all(reference.entity_id != entity_id for reference in dimension.entity_refs)
    ]
    return before - len(sketch.dimensions)


def dimension_measure_points(
    sketch: "SketchFeature", dimension: SketchDimension
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return local points used by the viewport annotation and hit test."""

    validate_dimension(sketch, dimension)
    if dimension.dimension_type == LENGTH:
        entity = _scalar_entity(sketch, dimension.entity_refs[0], SketchLine)
        return (entity.x1, entity.y1), (entity.x2, entity.y2)
    if dimension.dimension_type in {RADIUS, DIAMETER}:
        entity = _scalar_entity(sketch, dimension.entity_refs[0], SketchCircle)
        return (entity.cx, entity.cy), (entity.cx + entity.radius, entity.cy)
    return (
        _point_for_reference(sketch, dimension.entity_refs[0])[0],
        _point_for_reference(sketch, dimension.entity_refs[1])[0],
    )


def dimension_label_point(
    sketch: "SketchFeature", dimension: SketchDimension
) -> tuple[float, float]:
    if dimension.label_position is not None:
        return dimension.label_position
    first, second = dimension_measure_points(sketch, dimension)
    if dimension.dimension_type in {RADIUS, DIAMETER}:
        return second
    return ((first[0] + second[0]) * 0.5, (first[1] + second[1]) * 0.5)


def dimension_label(dimension: SketchDimension, measured_value: float | None = None) -> str:
    value = dimension.value if measured_value is None else measured_value
    suffix = " mm"
    if dimension.dimension_type == RADIUS:
        return f"R {value * 1000.0:.2f}{suffix}"
    if dimension.dimension_type == DIAMETER:
        return f"Ø {value * 1000.0:.2f}{suffix}"
    return f"{value * 1000.0:.2f}{suffix}"


def validate_dimensions(sketch: "SketchFeature") -> None:
    """Validate all dimensions and mark invalid ones for clear UI diagnostics."""

    for dimension in sketch.dimensions:
        try:
            validate_dimension(sketch, dimension)
            dimension.status = "OK"
            dimension.error_message = ""
        except DimensionError as exc:
            dimension.status = "INVALID"
            dimension.error_message = str(exc)
            raise
    for index, dimension in enumerate(sketch.dimensions):
        for other in sketch.dimensions[index + 1 :]:
            if _dimension_conflict_key(dimension) == _dimension_conflict_key(other):
                message = "Sketch contains conflicting driving dimensions."
                dimension.status = other.status = "INVALID"
                dimension.error_message = other.error_message = message
                raise DimensionError(message)
