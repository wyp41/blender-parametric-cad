"""Flat linked Part instances; independent of Blender and Feature History."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite

from .feature import new_uuid
from .transform import IDENTITY_MATRIX, Matrix4


def validate_instance_transform(value) -> Matrix4:
    """Return a finite rigid 4x4 matrix in meters (Rz @ Ry @ Rx convention)."""

    matrix = tuple(tuple(float(component) for component in row) for row in value)
    if len(matrix) != 4 or any(len(row) != 4 for row in matrix):
        raise ValueError("Instance transform must be a 4x4 matrix.")
    if not all(isfinite(component) for row in matrix for component in row):
        raise ValueError("Instance transform must be finite.")
    if matrix[3] != (0.0, 0.0, 0.0, 1.0):
        raise ValueError("Instance transform must be affine.")
    for i in range(3):
        for j in range(3):
            dot = sum(matrix[k][i] * matrix[k][j] for k in range(3))
            if abs(dot - float(i == j)) > 1e-6:
                raise ValueError("Instance transform must be rigid (no scale or shear).")
    determinant = sum(
        matrix[0][i] * (matrix[1][(i + 1) % 3] * matrix[2][(i + 2) % 3]
                        - matrix[1][(i + 2) % 3] * matrix[2][(i + 1) % 3])
        for i in range(3)
    )
    if abs(determinant - 1.0) > 1e-6:
        raise ValueError("Instance transform must have a proper rotation.")
    return matrix


@dataclass
class AssemblyInstance:
    """One placement of an original Part Studio, referenced by UUID."""

    id: str = field(default_factory=new_uuid)
    name: str = "Instance"
    part_studio_id: str = ""
    transform: Matrix4 = IDENTITY_MATRIX
    suppressed: bool = False

    def __post_init__(self) -> None:
        self.transform = validate_instance_transform(self.transform)


@dataclass
class Assembly:
    """An organizational container without CAD features or body validation."""

    id: str = field(default_factory=new_uuid)
    name: str = "Assembly 1"
    instances: list[AssemblyInstance] = field(default_factory=list)


class PartInUseError(ValueError):
    """Reject source deletion and expose every dependent Assembly/Instance UUID."""

    code = "PART_IN_USE"

    def __init__(self, part_id: str, references: list[dict[str, str]]):
        self.details = {"part_id": part_id, "references": references}
        super().__init__(f"PART_IN_USE: {part_id}: {references}")
