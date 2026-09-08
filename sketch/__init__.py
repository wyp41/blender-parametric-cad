"""Planar sketch data and profile detection."""

from .entities import SketchArc, SketchCircle, SketchEntity, SketchLine
from .edges import (
    EdgeCandidate,
    EdgeMatchTolerance,
    EdgeResolutionError,
    PersistentEdgeResolver,
    ResolvedEdge,
)
from .plane import (
    DerivedPlaneReference,
    PlaneReference,
    PlaneResolver,
    RegionHint,
    ResolvedPlane,
    SketchPlaneReference,
)
from .profile import ProfileDetector, ProfileLoop, SketchProfile
from .snapping import intersection_points, reference_points, snap_point, snap_targets
from .sketch import SketchFeature, sketch_normal, sketch_to_world

__all__ = [
    "ProfileDetector",
    "ProfileLoop",
    "PlaneResolver",
    "PlaneReference",
    "DerivedPlaneReference",
    "RegionHint",
    "ResolvedPlane",
    "SketchArc",
    "SketchCircle",
    "SketchEntity",
    "SketchFeature",
    "SketchLine",
    "SketchPlaneReference",
    "SketchProfile",
    "EdgeCandidate",
    "EdgeMatchTolerance",
    "EdgeResolutionError",
    "PersistentEdgeResolver",
    "ResolvedEdge",
    "intersection_points",
    "reference_points",
    "snap_point",
    "snap_targets",
    "sketch_normal",
    "sketch_to_world",
]
