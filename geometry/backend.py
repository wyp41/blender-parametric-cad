"""Geometry-kernel boundary consumed by the history evaluator."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..sketch.profile import SketchProfile
from ..sketch.sketch import SketchFeature
from ..core.references import TopoReference
from ..core.transform import Transform


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

    def revolve_profile(
        self,
        sketch: SketchFeature,
        profile: SketchProfile,
        axis_origin: tuple[float, float, float],
        axis_direction: tuple[float, float, float],
        angle: float,
    ) -> Any:
        """Create a solid by sweeping a closed profile around an axis."""

        raise NotImplementedError

    def register_extrude_provenance(
        self,
        body: Any,
        feature_id: str,
        profile: SketchProfile,
    ) -> None:
        """Record transient polygon-to-semantic-face provenance for a body."""

    def face_provenance(self, body: Any) -> dict[int, TopoReference]:
        """Return transient provenance for the current generated mesh."""

        return {}

    def boolean_difference(self, body: Any, tool: Any) -> Any:
        """Return a new body equal to body minus tool."""

        raise NotImplementedError

    def boolean_union(self, body: Any, tool: Any) -> Any:
        """Return a new body equal to the union of body and tool."""

        raise NotImplementedError

    def transform_body(self, body: Any, transform: Transform) -> Any:
        """Return ``body`` transformed by a persistent CAD rigid transform."""

        raise NotImplementedError

    def mirror_tool(
        self,
        tool: Any,
        plane_origin: tuple[float, float, float],
        plane_normal: tuple[float, float, float],
    ) -> Any:
        """Reflect a feature tool across a resolved semantic plane."""

        raise NotImplementedError
