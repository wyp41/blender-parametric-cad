"""Detection of one simple closed circle or connected line loop."""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose

from .entities import SketchCircle, SketchLine
from .sketch import SketchFeature

Point2D = tuple[float, float]


@dataclass(frozen=True)
class SketchProfile:
    kind: str
    points: tuple[Point2D, ...] = ()
    circle: tuple[float, float, float] | None = None


@dataclass(frozen=True)
class ProfileResult:
    success: bool
    profile: SketchProfile | None = None
    message: str = ""


class ProfileDetector:
    """Detect one non-branching, non-self-intersecting outer loop."""

    tolerance = 1e-7

    def detect(self, sketch: SketchFeature) -> ProfileResult:
        entities = [item for item in sketch.entities if not item.construction]
        if len(entities) == 1 and isinstance(entities[0], SketchCircle):
            circle = entities[0]
            if circle.radius > 0.0:
                return ProfileResult(
                    True,
                    SketchProfile("CIRCLE", circle=(circle.cx, circle.cy, circle.radius)),
                )

        if len(entities) >= 3 and all(isinstance(item, SketchLine) for item in entities):
            points = self._ordered_loop(entities)  # type: ignore[arg-type]
            if points is not None:
                kind = "RECTANGLE" if len(points) == 4 and self._is_rectangle(list(points)) else "POLYGON"
                return ProfileResult(True, SketchProfile(kind, points=points))

        return ProfileResult(
            False,
            message=(
                "Sketch does not contain a supported closed profile: use one simple "
                "circle or connected line loop."
            ),
        )

    def _ordered_loop(self, lines: list[SketchLine]) -> tuple[Point2D, ...] | None:
        endpoint_counts: dict[tuple[int, int], int] = {}
        for line in lines:
            for point in ((line.x1, line.y1), (line.x2, line.y2)):
                key = self._point_key(point)
                endpoint_counts[key] = endpoint_counts.get(key, 0) + 1
        if any(count != 2 for count in endpoint_counts.values()):
            return None

        unused = list(lines)
        first = unused.pop(0)
        ordered = [(first.x1, first.y1), (first.x2, first.y2)]

        while unused:
            current = ordered[-1]
            match_index = None
            next_point = None
            for index, line in enumerate(unused):
                start, end = (line.x1, line.y1), (line.x2, line.y2)
                if self._same_point(current, start):
                    match_index, next_point = index, end
                    break
                if self._same_point(current, end):
                    match_index, next_point = index, start
                    break
            if match_index is None or next_point is None:
                return None
            unused.pop(match_index)
            ordered.append(next_point)

        if not self._same_point(ordered[-1], ordered[0]):
            return None
        vertices = ordered[:-1]
        if len({self._point_key(point) for point in vertices}) != len(lines):
            return None
        if self._self_intersects(vertices):
            return None
        return tuple(vertices)

    def _same_point(self, left: Point2D, right: Point2D) -> bool:
        return isclose(left[0], right[0], abs_tol=self.tolerance) and isclose(
            left[1], right[1], abs_tol=self.tolerance
        )

    def _point_key(self, point: Point2D) -> tuple[int, int]:
        return (round(point[0] / self.tolerance), round(point[1] / self.tolerance))

    def _is_rectangle(self, points: list[Point2D]) -> bool:
        edges = [
            (
                points[(index + 1) % 4][0] - points[index][0],
                points[(index + 1) % 4][1] - points[index][1],
            )
            for index in range(4)
        ]
        if any(x * x + y * y <= self.tolerance**2 for x, y in edges):
            return False
        perpendicular = all(
            abs(edges[index][0] * edges[(index + 1) % 4][0]
                + edges[index][1] * edges[(index + 1) % 4][1])
            <= self.tolerance
            for index in range(4)
        )
        return perpendicular

    def _self_intersects(self, points: list[Point2D]) -> bool:
        count = len(points)
        for left in range(count):
            a, b = points[left], points[(left + 1) % count]
            for right in range(left + 1, count):
                if right in {left, (left + 1) % count} or (right + 1) % count == left:
                    continue
                c, d = points[right], points[(right + 1) % count]
                if self._segments_intersect(a, b, c, d):
                    return True
        return False

    def _segments_intersect(
        self, a: Point2D, b: Point2D, c: Point2D, d: Point2D
    ) -> bool:
        def cross(first: Point2D, second: Point2D, third: Point2D) -> float:
            return (second[0] - first[0]) * (third[1] - first[1]) - (
                second[1] - first[1]
            ) * (third[0] - first[0])

        ab_c, ab_d = cross(a, b, c), cross(a, b, d)
        cd_a, cd_b = cross(c, d, a), cross(c, d, b)
        return ab_c * ab_d < -(self.tolerance**2) and cd_a * cd_b < -(
            self.tolerance**2
        )
