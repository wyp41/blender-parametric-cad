"""Intersection and endpoint snapping helpers for planar sketch tools."""

from __future__ import annotations

from math import hypot, sqrt
from typing import Iterable

from .entities import SketchArc, SketchCircle, SketchEntity, SketchLine

Point2D = tuple[float, float]


def intersection_points(
    entities: Iterable[SketchEntity], tolerance: float = 1e-7
) -> tuple[Point2D, ...]:
    """Return unique intersections between visible line, circle, and arc entities.

    Endpoints that meet another entity are included as intersections.  Collinear
    or coincident curves do not produce an unbounded set of points; their finite
    endpoints are returned when they lie on the other curve.
    """

    material = [
        entity
        for entity in entities
        if not entity.construction
        and isinstance(entity, (SketchLine, SketchCircle, SketchArc))
    ]
    points: list[Point2D] = []
    for index, left in enumerate(material):
        for right in material[index + 1 :]:
            for point in _intersections(left, right, tolerance):
                _append_unique(points, point, tolerance)
    return tuple(points)


def snap_point(
    entities: Iterable[SketchEntity],
    point: Point2D,
    tolerance: float = 0.0015,
) -> Point2D:
    """Snap a point to nearby intersections, vertices, or curve projections."""

    material = [
        entity
        for entity in entities
        if not entity.construction
        and isinstance(entity, (SketchLine, SketchCircle, SketchArc))
    ]
    discrete: list[Point2D] = list(intersection_points(material))
    for entity in material:
        discrete.extend(_endpoints(entity))
    nearest_discrete = min(
        discrete,
        key=lambda candidate: hypot(point[0] - candidate[0], point[1] - candidate[1]),
        default=None,
    )
    if nearest_discrete is not None:
        distance = hypot(
            point[0] - nearest_discrete[0], point[1] - nearest_discrete[1]
        )
        if distance <= tolerance:
            return nearest_discrete

    projections: list[Point2D] = []
    for entity in material:
        projected = _project(entity, point, tolerance)
        if projected is not None:
            projections.append(projected)

    best = point
    best_distance = tolerance
    for candidate in projections:
        distance = hypot(point[0] - candidate[0], point[1] - candidate[1])
        if distance <= best_distance:
            best, best_distance = candidate, distance
    return best


def _intersections(
    left: SketchEntity, right: SketchEntity, tolerance: float
) -> tuple[Point2D, ...]:
    if isinstance(left, SketchLine) and isinstance(right, SketchLine):
        return _line_line(left, right, tolerance)
    if isinstance(left, SketchLine) and isinstance(right, (SketchCircle, SketchArc)):
        return _line_circle(left, right, tolerance)
    if isinstance(right, SketchLine) and isinstance(left, (SketchCircle, SketchArc)):
        return _line_circle(right, left, tolerance)
    if isinstance(left, (SketchCircle, SketchArc)) and isinstance(
        right, (SketchCircle, SketchArc)
    ):
        return _circle_circle(left, right, tolerance)
    return ()


def _line_line(
    left: SketchLine, right: SketchLine, tolerance: float
) -> tuple[Point2D, ...]:
    a, b = (left.x1, left.y1), (left.x2, left.y2)
    c, d = (right.x1, right.y1), (right.x2, right.y2)
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    denominator = _cross(r, s)
    offset = (c[0] - a[0], c[1] - a[1])
    if abs(denominator) > tolerance:
        t = _cross(offset, s) / denominator
        u = _cross(offset, r) / denominator
        if -tolerance <= t <= 1.0 + tolerance and -tolerance <= u <= 1.0 + tolerance:
            t = max(0.0, min(1.0, t))
            return ((a[0] + t * r[0], a[1] + t * r[1]),)
        return ()

    if abs(_cross(offset, r)) > tolerance:
        return ()
    points: list[Point2D] = []
    for point in (a, b, c, d):
        if _point_on_segment(point, a, b, tolerance) and _point_on_segment(
            point, c, d, tolerance
        ):
            _append_unique(points, point, tolerance)
    return tuple(points)


def _line_circle(
    line: SketchLine, curve: SketchCircle | SketchArc, tolerance: float
) -> tuple[Point2D, ...]:
    start, end = (line.x1, line.y1), (line.x2, line.y2)
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dy * dy
    radius = curve.radius
    if length_squared <= tolerance * tolerance or radius <= tolerance:
        return ()
    fx, fy = start[0] - curve.cx, start[1] - curve.cy
    linear = 2.0 * (fx * dx + fy * dy)
    constant = fx * fx + fy * fy - radius * radius
    discriminant = linear * linear - 4.0 * length_squared * constant
    if discriminant < -tolerance:
        return ()
    roots = (0.0,) if abs(discriminant) <= tolerance else (
        (-linear - sqrt(discriminant)) / (2.0 * length_squared),
        (-linear + sqrt(discriminant)) / (2.0 * length_squared),
    )
    points: list[Point2D] = []
    for root in roots:
        if -tolerance <= root <= 1.0 + tolerance:
            root = max(0.0, min(1.0, root))
            point = (start[0] + root * dx, start[1] + root * dy)
            if isinstance(curve, SketchArc) and not _angle_on_arc(
                curve, _angle(curve, point), tolerance
            ):
                continue
            _append_unique(points, point, tolerance)
    return tuple(points)


def _circle_circle(
    left: SketchCircle | SketchArc,
    right: SketchCircle | SketchArc,
    tolerance: float,
) -> tuple[Point2D, ...]:
    dx, dy = right.cx - left.cx, right.cy - left.cy
    distance = hypot(dx, dy)
    if distance <= tolerance:
        if abs(left.radius - right.radius) > tolerance:
            return ()
        points: list[Point2D] = []
        for point in (*_endpoints(left), *_endpoints(right)):
            if _point_on_curve(point, left, tolerance) and _point_on_curve(
                point, right, tolerance
            ):
                _append_unique(points, point, tolerance)
        return tuple(points)
    if distance > left.radius + right.radius + tolerance:
        return ()
    if distance < abs(left.radius - right.radius) - tolerance:
        return ()
    along = (left.radius * left.radius - right.radius * right.radius + distance * distance) / (
        2.0 * distance
    )
    height_squared = left.radius * left.radius - along * along
    if height_squared < -tolerance:
        return ()
    height = sqrt(max(0.0, height_squared))
    base = (left.cx + along * dx / distance, left.cy + along * dy / distance)
    offset = (-dy * height / distance, dx * height / distance)
    candidates = (
        (base[0] + offset[0], base[1] + offset[1]),
        (base[0] - offset[0], base[1] - offset[1]),
    )
    points: list[Point2D] = []
    for point in candidates:
        if isinstance(left, SketchArc) and not _angle_on_arc(
            left, _angle(left, point), tolerance
        ):
            continue
        if isinstance(right, SketchArc) and not _angle_on_arc(
            right, _angle(right, point), tolerance
        ):
            continue
        _append_unique(points, point, tolerance)
    return tuple(points)


def _endpoints(entity: SketchEntity) -> tuple[Point2D, ...]:
    if isinstance(entity, SketchLine):
        return ((entity.x1, entity.y1), (entity.x2, entity.y2))
    if isinstance(entity, SketchArc):
        return (entity.start_point, entity.end_point)
    return ()


def _project(
    entity: SketchEntity, point: Point2D, tolerance: float
) -> Point2D | None:
    if isinstance(entity, SketchLine):
        dx, dy = entity.x2 - entity.x1, entity.y2 - entity.y1
        length_squared = dx * dx + dy * dy
        if length_squared <= tolerance * tolerance:
            return (entity.x1, entity.y1)
        position = max(
            0.0,
            min(
                1.0,
                ((point[0] - entity.x1) * dx + (point[1] - entity.y1) * dy)
                / length_squared,
            ),
        )
        return (entity.x1 + position * dx, entity.y1 + position * dy)
    if isinstance(entity, (SketchCircle, SketchArc)):
        dx, dy = point[0] - entity.cx, point[1] - entity.cy
        distance = hypot(dx, dy)
        if distance <= tolerance:
            return None
        projected = (
            entity.cx + entity.radius * dx / distance,
            entity.cy + entity.radius * dy / distance,
        )
        if isinstance(entity, SketchArc) and not _angle_on_arc(
            entity, _angle(entity, projected), tolerance
        ):
            return None
        return projected
    return None


def _point_on_segment(point: Point2D, start: Point2D, end: Point2D, tolerance: float) -> bool:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= tolerance * tolerance:
        return hypot(point[0] - start[0], point[1] - start[1]) <= tolerance
    position = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared
    if position < -tolerance or position > 1.0 + tolerance:
        return False
    projected = (start[0] + position * dx, start[1] + position * dy)
    return hypot(point[0] - projected[0], point[1] - projected[1]) <= tolerance


def _point_on_curve(
    point: Point2D, curve: SketchCircle | SketchArc, tolerance: float
) -> bool:
    if abs(hypot(point[0] - curve.cx, point[1] - curve.cy) - curve.radius) > tolerance:
        return False
    return not isinstance(curve, SketchArc) or _angle_on_arc(
        curve, _angle(curve, point), tolerance
    )


def _angle(curve: SketchCircle | SketchArc, point: Point2D) -> float:
    from math import atan2

    return atan2(point[1] - curve.cy, point[0] - curve.cx)


def _angle_on_arc(arc: SketchArc, angle: float, tolerance: float) -> bool:
    from math import tau

    sweep = arc.end_angle - arc.start_angle
    if abs(sweep) <= tolerance:
        return True
    if sweep > 0.0:
        return (angle - arc.start_angle) % tau <= sweep + tolerance
    return (arc.start_angle - angle) % tau <= -sweep + tolerance


def _cross(left: Point2D, right: Point2D) -> float:
    return left[0] * right[1] - left[1] * right[0]


def _append_unique(points: list[Point2D], point: Point2D, tolerance: float) -> None:
    if any(hypot(point[0] - other[0], point[1] - other[1]) <= tolerance for other in points):
        return
    points.append(point)
