"""Native Blender driver helpers for prescribed planar Assembly motion.

This is a kinematic demonstration API, not a contact or joint solver. Expressions
are trusted Blender driver expressions using frame, sin, cos, sqrt, etc. Native
drivers persist in the .blend file without a Python frame-change callback.
"""
from .environments import instance_object


def set_planar_motion(instance_id, *, angle=None, x=None, y=None):
    """Drive local delta Z rotation (radians) and delta X/Y translation (meters)."""
    obj = instance_object(instance_id)
    if obj is None:
        raise ValueError(f'Assembly instance not found: {instance_id}')
    if angle is not None:
        obj.rotation_mode = 'QUATERNION'
        obj.driver_remove('delta_rotation_euler', 2)
        obj.delta_rotation_euler = (0, 0, 0)
        obj.delta_rotation_quaternion = (1, 0, 0, 0)
        for component, function in ((0, 'cos'), (3, 'sin')):
            driver = obj.driver_add('delta_rotation_quaternion', component).driver
            driver.expression = f'{function}(({angle})/2)'
    for index, expression in enumerate((x, y)):
        if expression is not None:
            obj.driver_add('delta_location', index).driver.expression = str(expression)
    # driver_add creates an identity map with keys at 0 and 1. F-curve key-time
    # snapping rounds small positive meter values to zero. With no mapping keys
    # Blender uses the driver result directly, preserving small clearances.
    for curve in obj.animation_data.drivers if obj.animation_data else ():
        if curve.data_path in ('delta_location', 'delta_rotation_quaternion'):
            curve.keyframe_points.clear()
            curve.update()
    return obj
