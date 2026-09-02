"""Blender-independent rigid transform math for CAD history features."""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, isfinite, sin
from typing import Iterable

Vector3 = tuple[float, float, float]
Matrix4 = tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]


IDENTITY_MATRIX: Matrix4 = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def matrix_multiply(left: Matrix4, right: Matrix4) -> Matrix4:
    """Return ``left @ right`` for two affine 4x4 matrices."""

    return tuple(
        tuple(
            sum(left[row][index] * right[index][column] for index in range(4))
            for column in range(4)
        )
        for row in range(4)
    )  # type: ignore[return-value]


def transform_point(matrix: Matrix4, point: Vector3) -> Vector3:
    """Apply an affine matrix to a point."""

    return tuple(
        matrix[row][0] * point[0]
        + matrix[row][1] * point[1]
        + matrix[row][2] * point[2]
        + matrix[row][3]
        for row in range(3)
    )  # type: ignore[return-value]


def transform_vector(matrix: Matrix4, vector: Vector3) -> Vector3:
    """Apply the linear part of an affine matrix to a vector."""

    return tuple(
        matrix[row][0] * vector[0]
        + matrix[row][1] * vector[1]
        + matrix[row][2] * vector[2]
        for row in range(3)
    )  # type: ignore[return-value]


def validate_vector(values: Iterable[float], label: str) -> Vector3:
    """Normalize a three-value vector and reject non-finite values."""

    try:
        result = tuple(float(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain three finite numbers.") from exc
    if len(result) != 3 or not all(isfinite(value) for value in result):
        raise ValueError(f"{label} must contain three finite numbers.")
    return result  # type: ignore[return-value]


@dataclass(frozen=True)
class Transform:
    """A persistent rigid transform expressed as translation and Euler angles.

    Translation is stored in meters and rotation in radians.  The rotation
    matrix is ``Rz @ Ry @ Rx`` (X, then Y, then Z), matching Blender's common
    XYZ Euler convention for the benchmark's Y-axis rotation case.
    """

    translation: Vector3 = (0.0, 0.0, 0.0)
    rotation: Vector3 = (0.0, 0.0, 0.0)

    def __post_init__(self) -> None:
        object.__setattr__(self, "translation", validate_vector(self.translation, "Translation"))
        object.__setattr__(self, "rotation", validate_vector(self.rotation, "Rotation"))

    @classmethod
    def identity(cls) -> "Transform":
        return cls()

    @property
    def matrix(self) -> Matrix4:
        tx, ty, tz = self.translation
        rx, ry, rz = self.rotation
        cx, sx = cos(rx), sin(rx)
        cy, sy = cos(ry), sin(ry)
        cz, sz = cos(rz), sin(rz)
        # Rz @ Ry @ Rx.
        return (
            (
                cz * cy,
                cz * sy * sx - sz * cx,
                cz * sy * cx + sz * sx,
                tx,
            ),
            (
                sz * cy,
                sz * sy * sx + cz * cx,
                sz * sy * cx - cz * sx,
                ty,
            ),
            (-sy, cy * sx, cy * cx, tz),
            (0.0, 0.0, 0.0, 1.0),
        )

    def apply_point(self, point: Vector3) -> Vector3:
        return transform_point(self.matrix, point)

    def apply_vector(self, vector: Vector3) -> Vector3:
        return transform_vector(self.matrix, vector)
