"""Blender-independent CAD document model.

Import concrete classes from their focused modules so extension cold-start does
not eagerly load the complete feature/evaluator graph.
"""

from .references import (
    AxisReference,
    EdgeReference,
    EdgeSignature,
    FaceReference,
    SelectionReference,
    SketchEntityReference,
    TopoReference,
)
from .transform import Matrix4, Transform, Vector3

__all__ = [
    "AxisReference",
    "EdgeReference",
    "EdgeSignature",
    "FaceReference",
    "SelectionReference",
    "SketchEntityReference",
    "TopoReference",
    "Matrix4",
    "Transform",
    "Vector3",
]
