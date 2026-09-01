"""Detection and editing helpers for closed 2D sketch profiles.

The first milestones only needed one circle or one line loop.  The detector now
also accepts mixed line/arc loops and planar graphs containing split lines.  A
profile can therefore contain several bounded regions; a deleted region is
identified by the stable UUIDs of the entities that bound it.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, hypot, isclose, pi
from typing import Iterable

from .entities import SketchArc, SketchCircle, SketchEntity, SketchLine
from .sketch import SketchFeature

Point2D = tuple[float, float]


@dataclass(frozen=True)
class ProfileLoop:
    """One tessellated closed region used by a geometry backend."""

    points: tuple[Point2D, ...] = ()
    entity_ids: tuple[str, ...] = ()
    region_id: str = ""
    circle: tuple[float, float, float] | None = None


@dataclass(frozen=True)
class SketchProfile:
    kind: str
    points: tuple[Point2D, ...] = ()
    circle: tuple[float, float, float] | None = None
    entity_ids: tuple[str, ...] = ()
    loops: tuple[ProfileLoop, ...] = ()
    region_ids: tuple[str, ...] = ()

    def iter_loops(self) -> tuple[ProfileLoop, ...]:
        """Return all profile loops, including legacy single-loop values."""

        if self.loops:
            return self.loops
        if self.circle is not None:
            return (ProfileLoop(circle=self.circle),)
        if self.points:
            return (ProfileLoop(self.points, self.entity_ids),)
        return ()


@dataclass(frozen=True)
class ProfileResult:
    success: bool
    profile: SketchProfile | None = None
    message: str = ""


@dataclass(frozen=True)
class _Curve:
    entity: SketchLine | SketchArc
    start: Point2D
    end: Point2D


class ProfileDetector:
    """Detect closed line/arc regions without relying on Blender topology."""

    tolerance = 1e-7
    arc_segments_per_radian = 12.0 / pi

    def detect(self, sketch: SketchFeature) -> ProfileResult:
        entities = [item for item in sketch.entities if not item.construction]
        return self.detect_entities(entities, sketch.deleted_regions)

    def detect_regions(self, sketch: SketchFeature) -> tuple[ProfileLoop, ...]:
        """Return every geometric region, including regions marked deleted."""

        entities = [item for item in sketch.entities if not item.construction]
        circles = [item for item in entities if isinstance(item, SketchCircle)]
        curves = [
            item for item in entities if isinstance(item, (SketchLine, SketchArc))
        ]
        if len(circles) + len(curves) != len(entities):
            return ()
        loops: list[ProfileLoop] = []
        loops.extend(self._circle_loops(circles))
        if curves:
            loops.extend(self._detect_loops(curves) or ())
        return tuple(loops)

    def detect_entities(
        self,
        entities: Iterable[SketchEntity],
        excluded_regions: Iterable[str] = (),
    ) -> ProfileResult:
        material = list(entities)
        excluded = set(excluded_regions)
        if not material:
            return self._invalid()

        circles = [item for item in material if isinstance(item, SketchCircle)]
        curves = [
            item
            for item in material
            if isinstance(item, (SketchLine, SketchArc))
        ]
        if len(circles) + len(curves) != len(material):
            return self._invalid("Sketch contains an unsupported entity type.")
        if circles:
            if not all(circle.radius > self.tolerance for circle in circles):
                return self._invalid("Circle radius must be greater than zero.")
            loops = list(self._circle_loops(circles, excluded))
            if curves:
                curve_loops = self._detect_loops(curves)
                if curve_loops is None:
                    return self._invalid()
                loops.extend(
                    loop for loop in curve_loops if loop.region_id not in excluded
                )
            if loops:
                kind = "CIRCLE" if len(loops) == 1 and not curves else "COMPOSITE"
                first = loops[0]
                return ProfileResult(
                    True,
                    SketchProfile(
                        kind,
                        points=first.points,
                        circle=first.circle,
                        entity_ids=first.entity_ids,
                        loops=tuple(loops),
                        region_ids=tuple(loop.region_id for loop in loops),
                    ),
                )
            return self._invalid("No active closed regions remain in the sketch.")

        if not curves:
            return self._invalid()
        loops = self._detect_loops(curves)
        if loops is None:
            return self._invalid()
        loops = tuple(loop for loop in loops if loop.region_id not in excluded)
        if not loops:
            return self._invalid("No active closed regions remain in the sketch.")

        first = loops[0]
        points = first.points
        if len(loops) > 1:
            kind = "COMPOSITE"
        elif any(isinstance(item, SketchArc) for item in curves):
            kind = "ARC_LOOP"
        elif len(points) == 4 and self._is_rectangle(list(points)):
            kind = "RECTANGLE"
        else:
            kind = "POLYGON"
        return ProfileResult(
            True,
            SketchProfile(
                kind,
                points=points,
                entity_ids=first.entity_ids,
                loops=loops,
                region_ids=tuple(loop.region_id for loop in loops),
            ),
        )

    def _circle_loops(
        self,
        circles: Iterable[SketchCircle],
        excluded_regions: Iterable[str] = (),
    ) -> list[ProfileLoop]:
        excluded = set(excluded_regions)
        return [
            ProfileLoop(
                circle=(circle.cx, circle.cy, circle.radius),
                region_id=self._region_id((circle.id,)),
            )
            for circle in circles
            if circle.radius > self.tolerance
            and self._region_id((circle.id,)) not in excluded
        ]

    def _detect_loops(
        self, entities: Iterable[SketchEntity]
    ) -> tuple[ProfileLoop, ...] | None:
        entity_list = list(entities)
        curves: list[_Curve] = []
        for entity in entity_list:
            if isinstance(entity, SketchLine):
                start, end = (entity.x1, entity.y1), (entity.x2, entity.y2)
            elif isinstance(entity, SketchArc):
                start, end = entity.start_point, entity.end_point
                if entity.radius <= self.tolerance:
                    return None
            else:
                continue
            if self._same_point(start, end):
                if isinstance(entity, SketchArc):
                    if len(entity_list) != 1:
                        return None
                    loop = self._loop_from_cycle(
                        curves=[_Curve(entity, start, end)],
                        cycle=[(0, self._point_key(start), self._point_key(end))],
                    )
                    return (loop,) if loop is not None else None
                return None
            curves.append(_Curve(entity, start, end))
        if not curves:
            return None
        curves = self._split_line_t_junctions(curves)

        adjacency: dict[tuple[int, int], list[int]] = {}
        for index, curve in enumerate(curves):
            adjacency.setdefault(self._point_key(curve.start), []).append(index)
            adjacency.setdefault(self._point_key(curve.end), []).append(index)

        components = self._components(curves, adjacency)
        all_loops: list[ProfileLoop] = []
        used_edges: set[int] = set()
        for component_nodes, component_edges in components:
            cycles = self._cycles(curves, adjacency, component_nodes, component_edges)
            if not cycles:
                return None
            if any(len(adjacency[node]) != 2 for node in component_nodes):
                # A connected split graph has one exterior cycle.  Only the
                # bounded cycles are profiles; the largest-area cycle is the
                # exterior boundary and is discarded.
                if len(cycles) > 1:
                    exterior = max(
                        cycles,
                        key=lambda cycle: abs(self._cycle_area(curves, cycle)),
                    )
                    cycles = [cycle for cycle in cycles if cycle != exterior]
            if not cycles:
                return None
            valid_loops: list[tuple[list[tuple[int, tuple[int, int], tuple[int, int]]], ProfileLoop]] = []
            for cycle in cycles:
                loop = self._loop_from_cycle(curves, cycle)
                if loop is None:
                    continue
                valid_loops.append((cycle, loop))
            if not valid_loops:
                return None
            for cycle, loop in valid_loops:
                all_loops.append(loop)
                used_edges.update(edge for edge, _start, _end in cycle)

        # A dangling non-construction entity must not silently disappear from
        # the profile.  This keeps the old open/branching validation behavior
        # while allowing lines that genuinely split a closed boundary.
        if used_edges != set(range(len(curves))):
            return None
        return tuple(all_loops)

    def _split_line_t_junctions(self, curves: list[_Curve]) -> list[_Curve]:
        """Split a boundary line when another line ends on its interior.

        This is deliberately limited to T-junctions.  Crossing two interiors
        remains invalid, preserving the existing self-intersection guard while
        making a sketched cut line work even when it lands on an edge midpoint.
        """

        splits: dict[int, list[tuple[float, Point2D]]] = {}
        lines = [
            (index, curve)
            for index, curve in enumerate(curves)
            if isinstance(curve.entity, SketchLine)
        ]
        for source_index, source in lines:
            for endpoint in (source.start, source.end):
                for target_index, target in lines:
                    if source_index == target_index:
                        continue
                    parameter = self._line_parameter(endpoint, target)
                    if parameter is None:
                        continue
                    splits.setdefault(target_index, []).append((parameter, endpoint))
        result: list[_Curve] = []
        for index, curve in enumerate(curves):
            points = [(0.0, curve.start), *splits.get(index, ()), (1.0, curve.end)]
            points.sort(key=lambda item: item[0])
            for (_left_t, left), (_right_t, right) in zip(points, points[1:]):
                if not self._same_point(left, right):
                    result.append(_Curve(curve.entity, left, right))
        return result

    def _line_parameter(self, point: Point2D, line: _Curve) -> float | None:
        dx, dy = line.end[0] - line.start[0], line.end[1] - line.start[1]
        length_squared = dx * dx + dy * dy
        if length_squared <= self.tolerance**2:
            return None
        parameter = (
            (point[0] - line.start[0]) * dx + (point[1] - line.start[1]) * dy
        ) / length_squared
        if parameter <= self.tolerance or parameter >= 1.0 - self.tolerance:
            return None
        projected = (
            line.start[0] + parameter * dx,
            line.start[1] + parameter * dy,
        )
        return parameter if hypot(projected[0] - point[0], projected[1] - point[1]) <= self.tolerance else None

    def _components(
        self,
        curves: list[_Curve],
        adjacency: dict[tuple[int, int], list[int]],
    ) -> list[tuple[set[tuple[int, int]], set[int]]]:
        components: list[tuple[set[tuple[int, int]], set[int]]] = []
        visited: set[tuple[int, int]] = set()
        for node in adjacency:
            if node in visited:
                continue
            nodes: set[tuple[int, int]] = set()
            edges: set[int] = set()
            stack = [node]
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                nodes.add(current)
                for edge in adjacency.get(current, ()):
                    edges.add(edge)
                    curve = curves[edge]
                    start_key = self._point_key(curve.start)
                    other = (
                        self._point_key(curve.end)
                        if current == start_key
                        else start_key
                    )
                    if other not in visited:
                        stack.append(other)
            components.append((nodes, edges))
        return components

    def _cycles(
        self,
        curves: list[_Curve],
        adjacency: dict[tuple[int, int], list[int]],
        nodes: set[tuple[int, int]],
        edges: set[int],
    ) -> list[list[tuple[int, tuple[int, int], tuple[int, int]]]]:
        cycles: dict[tuple[int, ...], list[tuple[int, tuple[int, int], tuple[int, int]]]] = {}
        max_length = len(edges)
        endpoint_keys: dict[int, tuple[tuple[int, int], tuple[int, int]]] = {}
        for edge in edges:
            incident = [node for node in nodes if edge in adjacency.get(node, ())]
            if len(incident) != 2:
                return []
            endpoint_keys[edge] = (incident[0], incident[1])

        def node_other(edge: int, node: tuple[int, int]) -> tuple[int, int]:
            start, end = endpoint_keys[edge]
            return end if node == start else start

        def visit(
            start: tuple[int, int],
            current: tuple[int, int],
            path_nodes: list[tuple[int, int]],
            path_edges: list[tuple[int, tuple[int, int], tuple[int, int]]],
        ) -> None:
            for edge in adjacency.get(current, ()):
                if edge not in edges:
                    continue
                if edge in {item[0] for item in path_edges}:
                    continue
                other = node_other(edge, current)
                if other == start:
                    if len(path_edges) >= 1:
                        cycle = path_edges + [(edge, current, other)]
                        key = tuple(sorted(item[0] for item in cycle))
                        cycles.setdefault(key, cycle)
                    continue
                if other in path_nodes or len(path_edges) >= max_length:
                    continue
                visit(
                    start,
                    other,
                    path_nodes + [other],
                    path_edges + [(edge, current, other)],
                )

        for start in sorted(nodes):
            visit(start, start, [start], [])
        return list(cycles.values())

    def _loop_from_cycle(
        self,
        curves: list[_Curve],
        cycle: list[tuple[int, tuple[int, int], tuple[int, int]]],
    ) -> ProfileLoop | None:
        points: list[Point2D] = []
        entity_ids: list[str] = []
        for edge_index, start_node, end_node in cycle:
            curve = curves[edge_index]
            segment = self._sample_curve(curve, start_node, end_node)
            if len(segment) < 2:
                return None
            points.extend(segment[:-1])
            entity_ids.extend([curve.entity.id] * (len(segment) - 1))
        if len(points) < 2:
            return None
        if abs(self._area(points)) <= self.tolerance**2 or self._self_intersects(points):
            return None
        region_id = self._region_id(entity_ids)
        return ProfileLoop(tuple(points), tuple(entity_ids), region_id)

    def _sample_curve(
        self,
        curve: _Curve,
        start_node: tuple[int, int],
        end_node: tuple[int, int],
    ) -> list[Point2D]:
        if isinstance(curve.entity, SketchLine):
            start, end = curve.start, curve.end
            if self._point_key(start) != start_node:
                start, end = end, start
            return [start, end]
        arc = curve.entity
        start_angle, end_angle = arc.start_angle, arc.end_angle
        if self._point_key(arc.start_point) != start_node:
            start_angle, end_angle = end_angle, start_angle
        sweep = end_angle - start_angle
        if abs(sweep) <= self.tolerance and self._same_point(curve.start, curve.end):
            sweep = 2.0 * pi
        count = max(4, int(ceil(abs(sweep) * self.arc_segments_per_radian)))
        return [
            arc.point(start_angle + sweep * index / count)
            for index in range(count + 1)
        ]

    def _cycle_area(
        self,
        curves: list[_Curve],
        cycle: list[tuple[int, tuple[int, int], tuple[int, int]]],
    ) -> float:
        loop = self._loop_from_cycle(curves, cycle)
        return self._area(loop.points) if loop is not None else 0.0

    def _region_id(self, entity_ids: Iterable[str]) -> str:
        return "REGION:" + ",".join(sorted(set(entity_ids)))

    def _invalid(self, message: str | None = None) -> ProfileResult:
        return ProfileResult(
            False,
            message=message
            or (
                "Sketch does not contain a supported closed profile: use a circle, "
                "a connected line/arc loop, or a split closed boundary."
            ),
        )

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
        return all(
            abs(
                edges[index][0] * edges[(index + 1) % 4][0]
                + edges[index][1] * edges[(index + 1) % 4][1]
            )
            <= self.tolerance
            for index in range(4)
        )

    # Compatibility helpers retained for callers from the first milestones.
    def _ordered_loop(self, lines: list[SketchLine]) -> tuple[Point2D, ...] | None:
        ordered = self._ordered_loop_lines(lines)
        return tuple(item[1] for item in ordered) if ordered is not None else None

    def _ordered_loop_lines(
        self, lines: list[SketchLine]
    ) -> list[tuple[SketchLine, Point2D, Point2D]] | None:
        endpoint_counts: dict[tuple[int, int], int] = {}
        for line in lines:
            for point in ((line.x1, line.y1), (line.x2, line.y2)):
                key = self._point_key(point)
                endpoint_counts[key] = endpoint_counts.get(key, 0) + 1
        if any(count != 2 for count in endpoint_counts.values()):
            return None

        unused = list(lines)
        first = unused.pop(0)
        ordered = [(first, (first.x1, first.y1), (first.x2, first.y2))]
        while unused:
            current = ordered[-1][2]
            match_index = None
            next_entry = None
            for index, line in enumerate(unused):
                start, end = (line.x1, line.y1), (line.x2, line.y2)
                if self._same_point(current, start):
                    match_index, next_entry = index, (line, start, end)
                    break
                if self._same_point(current, end):
                    match_index, next_entry = index, (line, end, start)
                    break
            if match_index is None or next_entry is None:
                return None
            unused.pop(match_index)
            ordered.append(next_entry)
        if not self._same_point(ordered[-1][2], ordered[0][1]):
            return None
        vertices = [item[1] for item in ordered]
        if len({self._point_key(point) for point in vertices}) != len(lines):
            return None
        if self._self_intersects(vertices):
            return None
        return ordered

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

    @staticmethod
    def area(points: Iterable[Point2D]) -> float:
        """Signed area helper for UI region hit testing."""

        values = list(points)
        return ProfileDetector._area(values)

    @staticmethod
    def _area(points: list[Point2D]) -> float:
        return 0.5 * sum(
            points[index][0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * points[index][1]
            for index in range(len(points))
        )

    @staticmethod
    def point_in_loop(point: Point2D, loop: ProfileLoop) -> bool:
        """Return whether a local sketch point lies inside a line/arc loop."""

        if loop.circle is not None:
            cx, cy, radius = loop.circle
            dx, dy = point[0] - cx, point[1] - cy
            return dx * dx + dy * dy < radius * radius
        inside = False
        points = loop.points
        for index, (x1, y1) in enumerate(points):
            x2, y2 = points[(index + 1) % len(points)]
            if (y1 > point[1]) != (y2 > point[1]):
                x_at_y = (x2 - x1) * (point[1] - y1) / (y2 - y1) + x1
                if point[0] < x_at_y:
                    inside = not inside
        return inside
