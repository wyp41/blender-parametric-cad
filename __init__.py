"""Blender Parametric CAD extension entry point."""

from __future__ import annotations

def register() -> None:
    import bpy

    from .blender import properties
    from .blender.operators import (
        export,
        extrude,
        part,
        revolve,
        selection,
        sketch,
        sketch_tools,
    )
    from .blender.ui import panels
    from .blender.viewport import sketch_overlay

    properties.register()
    for group in (
        part.CLASSES,
        selection.CLASSES,
        export.CLASSES,
        sketch.CLASSES,
        sketch_tools.CLASSES,
        extrude.CLASSES,
        revolve.CLASSES,
        panels.CLASSES,
    ):
        for cls in group:
            bpy.utils.register_class(cls)
    sketch_overlay.start()


def unregister() -> None:
    import bpy

    from .blender import properties
    from .blender.operators import (
        export,
        extrude,
        part,
        revolve,
        selection,
        sketch,
        sketch_tools,
    )
    from .blender.ui import panels
    from .blender.viewport import sketch_overlay

    sketch_overlay.stop()
    groups = (
        part.CLASSES,
        selection.CLASSES,
        export.CLASSES,
        sketch.CLASSES,
        sketch_tools.CLASSES,
        extrude.CLASSES,
        revolve.CLASSES,
        panels.CLASSES,
    )
    for group in reversed(groups):
        for cls in reversed(group):
            bpy.utils.unregister_class(cls)
    properties.unregister()
