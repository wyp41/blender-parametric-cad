"""Blender Parametric CAD extension entry point."""

from __future__ import annotations


def register() -> None:
    import bpy

    from .blender import adapter
    from .blender import properties
    from .blender.operators import (
        export,
        extrude,
        part,
        revolve,
        selection,
        sketch,
        sketch_tools,
        history,
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
        history.CLASSES,
        panels.CLASSES,
    ):
        for cls in group:
            bpy.utils.register_class(cls)
    sketch_overlay.start()
    history.register_keymaps()
    adapter.register_handlers()


def unregister() -> None:
    import bpy

    from .blender import adapter
    from .blender import properties
    from .blender.operators import (
        export,
        extrude,
        part,
        revolve,
        selection,
        sketch,
        sketch_tools,
        history,
    )
    from .blender.ui import panels
    from .blender.viewport import sketch_overlay

    adapter.unregister_handlers()
    history.unregister_keymaps()
    sketch_overlay.stop()
    groups = (
        part.CLASSES,
        selection.CLASSES,
        export.CLASSES,
        sketch.CLASSES,
        sketch_tools.CLASSES,
        extrude.CLASSES,
        revolve.CLASSES,
        history.CLASSES,
        panels.CLASSES,
    )
    for group in reversed(groups):
        for cls in reversed(group):
            bpy.utils.unregister_class(cls)
    properties.unregister()
