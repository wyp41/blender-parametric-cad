"""Stable semantic references used by viewport-driven CAD tools."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Any


def _canonical_direction(values: tuple[float, float, float]) -> tuple[float, float, float]:
    if len(values) != 3:
        raise ValueError("Edge direction must contain three finite non-zero numbers.")
    length = sqrt(sum(value * value for value in values))
    if length <= 1e-12 or not all(isfinite(value) for value in values):
        raise ValueError("Edge direction must contain three finite non-zero numbers.")
    direction = tuple(value / length for value in values)
    for value in direction:
        if abs(value) <= 1e-12:
            continue
        if value < 0.0:
            direction = tuple(-component for component in direction)
        break
    return direction


@dataclass(frozen=True)
class EdgeSignature:
    """Canonical producer-local geometry for one supported straight edge.

    ``local_line_offset`` is the closest point on the infinite line to the
    local origin.  It therefore remains unchanged when the two endpoints are
    supplied in the opposite order and is not a frozen world-space position.
    The midpoint and length are only disambiguation hints.
    """

    local_direction: tuple[float, float, float]
    local_line_offset: tuple[float, float, float]
    midpoint_hint: tuple[float, float, float]
    length_hint: float

    def __post_init__(self) -> None:
        direction = _canonical_direction(tuple(float(value) for value in self.local_direction))
        line_offset = tuple(float(value) for value in self.local_line_offset)
        midpoint = tuple(float(value) for value in self.midpoint_hint)
        if len(line_offset) != 3 or len(midpoint) != 3:
            raise ValueError("Edge signature points must contain three values.")
        if not all(isfinite(value) for value in (*line_offset, *midpoint)):
            raise ValueError("Edge signature points must be finite.")
        # Store the closest point on the line, which removes any component
        # parallel to the direction and makes equivalent representations equal.
        projection = sum(line_offset[index] * direction[index] for index in range(3))
        line_offset = tuple(
            line_offset[index] - projection * direction[index] for index in range(3)
        )
        length = float(self.length_hint)
        if not isfinite(length) or length <= 0.0:
            raise ValueError("Edge signature length must be finite and greater than zero.")
        object.__setattr__(self, "local_direction", direction)
        object.__setattr__(self, "local_line_offset", line_offset)
        object.__setattr__(self, "midpoint_hint", midpoint)
        object.__setattr__(self, "length_hint", length)

    def to_dict(self) -> dict[str, Any]:
        return {
            "local_direction": list(self.local_direction),
            "local_line_offset": list(self.local_line_offset),
            "midpoint_hint": list(self.midpoint_hint),
            "length_hint": self.length_hint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "EdgeSignature | None":
        if not data:
            return None
        return cls(
            local_direction=tuple(float(value) for value in data.get("local_direction", ())),
            local_line_offset=tuple(float(value) for value in data.get("local_line_offset", ())),
            midpoint_hint=tuple(float(value) for value in data.get("midpoint_hint", ())),
            length_hint=float(data.get("length_hint", 0.0)),
        )


@dataclass(frozen=True)
class FaceReference:
    """Semantic producer and source entity, independent of display topology."""

    producer_feature_id: str
    role: str
    source_entity_id: str | None = None

    @property
    def reference_type(self) -> str:
        return "FACE"

    @property
    def feature_id(self) -> str:
        return self.producer_feature_id

    def to_dict(self) -> dict[str, Any]:
        return {"producer_feature_id": self.producer_feature_id,
                "role": self.role, "source_entity_id": self.source_entity_id}

    @classmethod
    def from_dict(cls, data):
        return cls(data.get("producer_feature_id") or data["feature_id"],
                   data["role"], data.get("source_entity_id"))


@dataclass(frozen=True)
class EdgeReference:
    """Persistent semantic identity for a supported straight CAD edge.

    The adjacent planes and producer-local line signature are persistent.  A
    Blender mesh edge index is intentionally absent; indices belong only to
    the runtime candidate cache rebuilt from the current display mesh.
    """

    producer_feature_id: str
    role: str | None = None
    adjacent_plane_refs: tuple[Any | None, Any | None] = (None, None)
    source_entity_ids: tuple[str, ...] = ()
    local_signature: EdgeSignature | None = None

    def __post_init__(self) -> None:
        if not self.producer_feature_id:
            raise ValueError("Edge reference requires a producer feature UUID.")
        planes = tuple(self.adjacent_plane_refs)
        if len(planes) != 2:
            raise ValueError("Edge reference requires two adjacent-plane slots.")
        source_ids = tuple(
            dict.fromkeys(str(value) for value in self.source_entity_ids if value)
        )
        object.__setattr__(self, "producer_feature_id", str(self.producer_feature_id))
        object.__setattr__(self, "adjacent_plane_refs", planes)
        object.__setattr__(self, "source_entity_ids", source_ids)

    @property
    def reference_type(self) -> str:
        return "EDGE"

    @property
    def feature_id(self) -> str:
        return self.producer_feature_id

    def to_dict(self) -> dict[str, Any]:
        from .serialization import plane_reference_to_dict

        return {
            "reference_type": self.reference_type,
            "producer_feature_id": self.producer_feature_id,
            "role": self.role,
            "adjacent_plane_refs": [
                plane_reference_to_dict(reference) if reference is not None else None
                for reference in self.adjacent_plane_refs
            ],
            "source_entity_ids": list(self.source_entity_ids),
            "local_signature": (
                self.local_signature.to_dict() if self.local_signature is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EdgeReference":
        from .serialization import plane_reference_from_dict

        if "mesh_edge_index" in data or "edge_index" in data:
            raise ValueError("Persistent EdgeReference cannot contain a Blender edge index.")
        planes = data.get("adjacent_plane_refs", ())
        if len(planes) != 2:
            planes = tuple(planes) + (None,) * (2 - len(planes))
        return cls(
            producer_feature_id=str(data.get("producer_feature_id") or data.get("feature_id") or ""),
            role=data.get("role"),
            adjacent_plane_refs=tuple(
                plane_reference_from_dict(value) if value else None for value in planes[:2]
            ),
            source_entity_ids=tuple(data.get("source_entity_ids", ())),
            local_signature=EdgeSignature.from_dict(data.get("local_signature")),
        )


@dataclass(frozen=True)
class SketchEntityReference:
    """Persistent reference to a Sketch entity or one of its sub-elements.

    The UUIDs belong to the CAD Sketch model.  They are deliberately
    independent of Blender curve/mesh elements and therefore remain valid
    after a rebuild or a ``.blend`` reload.
    """

    sketch_id: str
    entity_id: str
    sub_element: str | None = None

    _SUB_ELEMENTS = frozenset({None, "START", "END", "CENTER", "ENTITY"})

    def __post_init__(self) -> None:
        sketch_id = str(self.sketch_id)
        entity_id = str(self.entity_id)
        sub_element = None if self.sub_element in {None, ""} else str(self.sub_element).upper()
        if not sketch_id or not entity_id:
            raise ValueError("Sketch entity references require Sketch and entity UUIDs.")
        if sub_element not in self._SUB_ELEMENTS:
            raise ValueError(f"Unsupported Sketch entity sub-element: {sub_element!r}")
        object.__setattr__(self, "sketch_id", sketch_id)
        object.__setattr__(self, "entity_id", entity_id)
        object.__setattr__(self, "sub_element", sub_element)

    @property
    def reference_type(self) -> str:
        return "SKETCH_ENTITY"

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_type": self.reference_type,
            "sketch_id": self.sketch_id,
            "entity_id": self.entity_id,
            "sub_element": self.sub_element,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SketchEntityReference":
        if not isinstance(data, dict):
            raise ValueError("Sketch entity reference must be a JSON object.")
        return cls(
            sketch_id=str(data.get("sketch_id") or ""),
            entity_id=str(data.get("entity_id") or ""),
            sub_element=data.get("sub_element"),
        )


@dataclass(frozen=True)
class TopoReference:
    """A persistent reference to a supported generated face."""

    feature_id: str
    role: str
    source_entity_id: str | None = None
    reference_type: str = "FACE"

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "reference_type": self.reference_type,
            "feature_id": self.feature_id,
            "role": self.role,
        }
        if self.source_entity_id is not None:
            data["source_entity_id"] = self.source_entity_id
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TopoReference":
        return cls(
            feature_id=str(data.get("producer_feature_id") or data["feature_id"]),
            role=str(data["role"]),
            source_entity_id=data.get("source_entity_id"),
            reference_type=str(data.get("reference_type", "FACE")),
        )


@dataclass(frozen=True)
class AxisReference:
    """A persistent datum-axis or SketchLine axis reference."""

    reference_type: str = "DATUM_AXIS"
    axis: str | None = "Z"
    sketch_id: str | None = None
    entity_id: str | None = None
    direction: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_type": self.reference_type,
            "axis": self.axis,
            "sketch_id": self.sketch_id,
            "entity_id": self.entity_id,
            "direction": -1 if self.direction < 0 else 1,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AxisReference":
        return cls(
            reference_type=str(data.get("reference_type", "DATUM_AXIS")),
            axis=data.get("axis"),
            sketch_id=data.get("sketch_id"),
            entity_id=data.get("entity_id"),
            direction=-1 if int(data.get("direction", 1) or 1) < 0 else 1,
        )


@dataclass(frozen=True)
class SelectionReference:
    """Generic selection payload reusable by future CAD tools."""

    selection_type: str
    topo_reference: TopoReference | None = None
    axis_reference: AxisReference | None = None
    sketch_id: str | None = None
    entity_id: str | None = None
