"""Geometry-kernel boundary consumed by the history evaluator."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..sketch.profile import SketchProfile
from ..sketch.sketch import SketchFeature


class GeometryBackend(ABC):
    """Interface that can later be implemented by an exact CAD kernel."""

    @abstractmethod
    def create_extrusion(
        self,
        sketch: SketchFeature,
        profile: SketchProfile,
        distance: float,
        direction: int,
    ) -> Any:
        raise NotImplementedError

    def create_extrusion_tool(
        self,
        sketch: SketchFeature,
        profile: SketchProfile,
        body: Any,
        direction: int,
    ) -> Any:
        """Create a cutter spanning the current body in the sketch normal direction."""

        raise NotImplementedError

    def create_blind_extrusion_tool(
        self,
        sketch: SketchFeature,
        profile: SketchProfile,
        distance: float,
        direction: int,
    ) -> Any:
        """Create a finite removal tool with the requested pocket depth."""

        return self.create_extrusion(sketch, profile, distance, direction)

    def boolean_difference(self, body: Any, tool: Any) -> Any:
        """Return a new body equal to body minus tool."""

        raise NotImplementedError

    def boolean_union(self, body: Any, tool: Any) -> Any:
        """Return a new body equal to the union of body and tool."""

        raise NotImplementedError
