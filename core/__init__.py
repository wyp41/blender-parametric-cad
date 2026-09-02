"""Blender-independent CAD document model.

Import concrete classes from their focused modules so extension cold-start does
not eagerly load the complete feature/evaluator graph.
"""

from .references import AxisReference, SelectionReference, TopoReference
from .transform import Matrix4, Transform, Vector3

__all__ = [
    "AxisReference",
    "SelectionReference",
    "TopoReference",
    "Matrix4",
    "Transform",
    "Vector3",
]
