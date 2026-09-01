"""Projection between 3D viewport rays and 2D sketch coordinates."""

from __future__ import annotations

from bpy_extras import view3d_utils
from mathutils import Vector

from ...sketch.sketch import SketchFeature, sketch_normal


def screen_to_sketch(context, event, sketch: SketchFeature) -> tuple[float, float] | None:
    region = context.region
    region_3d = context.space_data.region_3d
    coordinate = (event.mouse_region_x, event.mouse_region_y)
    ray_origin = view3d_utils.region_2d_to_origin_3d(region, region_3d, coordinate)
    ray_direction = view3d_utils.region_2d_to_vector_3d(region, region_3d, coordinate)
    plane_origin = Vector(sketch.origin)
    normal = Vector(sketch_normal(sketch))
    denominator = ray_direction.dot(normal)
    if abs(denominator) < 1e-9:
        return None
    intersection = ray_origin + ray_direction * (
        (plane_origin - ray_origin).dot(normal) / denominator
    )
    relative = intersection - plane_origin
    return relative.dot(Vector(sketch.x_axis)), relative.dot(Vector(sketch.y_axis))
