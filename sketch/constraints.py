"""Small persistent Sketch constraint model for the M9C solver."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from ..core.feature import new_uuid
from ..core.references import SketchEntityReference
from .entities import SketchCircle, SketchLine

if TYPE_CHECKING:
    from .sketch import SketchFeature


CONSTRAINT_TYPES = (
    "COINCIDENT",
    "HORIZONTAL",
    "VERTICAL",
    "PARALLEL",
    "PERPENDICULAR",
    "EQUAL",
)


class ConstraintError(ValueError):
    """An invalid or unsupported Sketch constraint."""

    def __init__(self, message: str, status: str = "INVALID_REFERENCE") -> None:
        super().__init__(message)
        self.status = status


@dataclass
class SketchConstraint:
    """Persistent constraint expressed only with Sketch entity UUIDs."""

    id: str = field(default_factory=new_uuid)
    constraint_type: str = "COINCIDENT"
    entity_refs: list[SketchEntityReference] = field(default_factory=list)
    enabled: bool = True

    def __post_init__(self) -> None:
        self.id = str(self.id or new_uuid())
        self.constraint_type = str(self.constraint_type).upper()
        if self.constraint_type not in CONSTRAINT_TYPES:
            raise ValueError(f"Unsupported Sketch constraint: {self.constraint_type!r}")
        self.entity_refs = [
            ref if isinstance(ref, SketchEntityReference)
            else SketchEntityReference.from_dict(ref)
            for ref in self.entity_refs
        ]
        self.enabled = bool(self.enabled)


def constraint_to_dict(constraint: SketchConstraint) -> dict[str, Any]:
    return {
        "id": constraint.id,
        "constraint_type": constraint.constraint_type,
        "entity_refs": [reference.to_dict() for reference in constraint.entity_refs],
        "enabled": bool(constraint.enabled),
    }


def constraint_from_dict(data: dict[str, Any]) -> SketchConstraint:
    if not isinstance(data, dict):
        raise ValueError("Sketch constraint must be a JSON object.")
    return SketchConstraint(
        id=str(data.get("id") or new_uuid()),
        constraint_type=str(data.get("constraint_type", data.get("type", "COINCIDENT"))),
        entity_refs=[
            SketchEntityReference.from_dict(item)
            for item in data.get("entity_refs", ())
        ],
        enabled=bool(data.get("enabled", True)),
    )


def remove_constraints_for_entity(sketch: "SketchFeature", entity_id: str) -> int:
    """Remove constraints that would otherwise retain a dangling UUID."""

    before = len(sketch.constraints)
    sketch.constraints = [
        constraint
        for constraint in sketch.constraints
        if all(reference.entity_id != entity_id for reference in constraint.entity_refs)
    ]
    return before - len(sketch.constraints)


def _entity_for_reference(sketch: "SketchFeature", reference: SketchEntityReference):
    if reference.sketch_id != sketch.id:
        raise ConstraintError(
            f"Reference belongs to Sketch {reference.sketch_id[:8]}, not {sketch.id[:8]}."
        )
    entity = next((item for item in sketch.entities if item.id == reference.entity_id), None)
    if entity is None:
        raise ConstraintError(
            f"Sketch entity reference {reference.entity_id[:8]} is missing."
        )
    return entity


def validate_constraint(sketch: "SketchFeature", constraint: SketchConstraint) -> None:
    """Validate a constraint's references without changing Sketch geometry."""

    refs = constraint.entity_refs
    kind = constraint.constraint_type
    if kind in {"HORIZONTAL", "VERTICAL"}:
        if len(refs) != 1:
            raise ConstraintError(f"{kind.title()} requires one line reference.")
        entity = _entity_for_reference(sketch, refs[0])
        if not isinstance(entity, SketchLine) or refs[0].sub_element not in {None, "", "ENTITY"}:
            raise ConstraintError(f"{kind.title()} only supports a whole SketchLine.")
        return
    if kind == "COINCIDENT":
        if len(refs) != 2:
            raise ConstraintError("Coincident requires two point references.")
        for reference in refs:
            entity = _entity_for_reference(sketch, reference)
            valid = (
                isinstance(entity, SketchLine) and reference.sub_element in {"START", "END"}
            ) or (
                isinstance(entity, SketchCircle) and reference.sub_element == "CENTER"
            )
            if not valid:
                raise ConstraintError(
                    "Coincident supports Line.START, Line.END, and Circle.CENTER."
                )
        return
    if kind in {"PARALLEL", "PERPENDICULAR"}:
        if len(refs) != 2:
            raise ConstraintError(f"{kind.title()} requires two line references.")
        if any(
            not isinstance(_entity_for_reference(sketch, reference), SketchLine)
            or reference.sub_element not in {None, "", "ENTITY"}
            for reference in refs
        ):
            raise ConstraintError(f"{kind.title()} only supports whole SketchLines.")
        return
    if kind == "EQUAL":
        if len(refs) != 2:
            raise ConstraintError("Equal requires two whole entity references.")
        entities = [_entity_for_reference(sketch, reference) for reference in refs]
        if any(reference.sub_element not in {None, "", "ENTITY"} for reference in refs):
            raise ConstraintError("Equal only supports whole entity references.")
        if not (
            all(isinstance(entity, SketchLine) for entity in entities)
            or all(isinstance(entity, SketchCircle) for entity in entities)
        ):
            raise ConstraintError("Equal supports Line + Line or Circle + Circle.")
        return
    raise ConstraintError(f"Unsupported Sketch constraint: {kind!r}")


def validate_constraints(sketch: "SketchFeature") -> None:
    for constraint in sketch.constraints:
        validate_constraint(sketch, constraint)
