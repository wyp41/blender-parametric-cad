"""Blender-independent 2D sketch entities, stored in meters."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import cos, sin

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


@dataclass
class SketchArc(SketchEntity):
    """A circular arc in the sketch's local 2D coordinate system.

    Angles are stored in radians and increase counter-clockwise.  Keeping the
    two angles instead of a derived sweep preserves the entity's endpoints and
    gives the profile detector a stable way to join arcs to line entities.
    """

    entity_type: str = field(default="ARC", init=False)
    cx: float = 0.0
    cy: float = 0.0
    radius: float = 0.0
    start_angle: float = 0.0
    end_angle: float = 0.0

    def point(self, angle: float) -> tuple[float, float]:
        return (
            self.cx + self.radius * cos(angle),
            self.cy + self.radius * sin(angle),
        )

    @property
    def start_point(self) -> tuple[float, float]:
        return self.point(self.start_angle)

    @property
    def end_point(self) -> tuple[float, float]:
        return self.point(self.end_angle)
