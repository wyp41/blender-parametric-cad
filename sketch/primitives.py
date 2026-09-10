"""Persistent semantic metadata for high-level Sketch primitives.

Primitive metadata is deliberately a thin layer over the ordinary Sketch
entities.  The four rectangle sides remain normal :class:`SketchLine`
objects, with their own UUIDs, so every existing profile, dimension, and
constraint tool can continue to operate on them directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.feature import new_uuid


@dataclass
class RectangleDefinition:
    """Persistent identity for one semantic rectangle.

    Coordinates and dimensions are not duplicated here.  The referenced
    SketchLines contain the geometry and the optional associated driving
    dimensions contain width/height values.  This avoids two competing
    sources of truth while still making the primitive discoverable over MCP.
    """

    id: str = field(default_factory=new_uuid)
    bottom_line_id: str = ""
    right_line_id: str = ""
    top_line_id: str = ""
    left_line_id: str = ""
    anchor_mode: str = "CORNER"
    width_dimension_id: str | None = None
    height_dimension_id: str | None = None

    def __post_init__(self) -> None:
        self.id = str(self.id or new_uuid())
        self.anchor_mode = str(self.anchor_mode or "CORNER").upper()
        if self.anchor_mode not in {"CORNER", "CENTER"}:
            raise ValueError(f"Unsupported rectangle anchor mode: {self.anchor_mode}")
        for name in (
            "bottom_line_id",
            "right_line_id",
            "top_line_id",
            "left_line_id",
        ):
            setattr(self, name, str(getattr(self, name) or ""))
        self.width_dimension_id = (
            str(self.width_dimension_id) if self.width_dimension_id else None
        )
        self.height_dimension_id = (
            str(self.height_dimension_id) if self.height_dimension_id else None
        )

    @property
    def entity_ids(self) -> tuple[str, str, str, str]:
        return (
            self.bottom_line_id,
            self.right_line_id,
            self.top_line_id,
            self.left_line_id,
        )

    def contains_entity(self, entity_id: str) -> bool:
        return str(entity_id) in self.entity_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "primitive_type": "RECTANGLE",
            "anchor_mode": self.anchor_mode,
            "entity_ids": {
                "bottom": self.bottom_line_id,
                "right": self.right_line_id,
                "top": self.top_line_id,
                "left": self.left_line_id,
            },
            "width_dimension_id": self.width_dimension_id,
            "height_dimension_id": self.height_dimension_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RectangleDefinition":
        if not isinstance(data, dict):
            raise ValueError("Rectangle definition must be a JSON object.")
        entity_ids = data.get("entity_ids") or {}
        if isinstance(entity_ids, (list, tuple)):
            entity_ids = {
                name: entity_ids[index] if index < len(entity_ids) else ""
                for index, name in enumerate(("bottom", "right", "top", "left"))
            }
        return cls(
            id=str(data.get("id") or new_uuid()),
            bottom_line_id=str(data.get("bottom_line_id") or entity_ids.get("bottom") or ""),
            right_line_id=str(data.get("right_line_id") or entity_ids.get("right") or ""),
            top_line_id=str(data.get("top_line_id") or entity_ids.get("top") or ""),
            left_line_id=str(data.get("left_line_id") or entity_ids.get("left") or ""),
            anchor_mode=str(data.get("anchor_mode", "CORNER")),
            width_dimension_id=data.get("width_dimension_id"),
            height_dimension_id=data.get("height_dimension_id"),
        )
