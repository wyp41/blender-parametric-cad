"""Blender-independent 2D sketch entities, stored in meters."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.feature import new_uuid


@dataclass
class SketchEntity:
    id: str = field(default_factory=new_uuid)
    entity_type: str = field(default="ENTITY", init=False)
    construction: bool = False


@dataclass
class SketchLine(SketchEntity):
    entity_type: str = field(default="LINE", init=False)
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0


@dataclass
class SketchCircle(SketchEntity):
    entity_type: str = field(default="CIRCLE", init=False)
    cx: float = 0.0
    cy: float = 0.0
    radius: float = 0.0
