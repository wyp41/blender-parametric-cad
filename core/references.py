"""Stable semantic references used by viewport-driven CAD tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
            feature_id=str(data["feature_id"]),
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
