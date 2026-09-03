"""Blender Parametric CAD extension entry point."""

from __future__ import annotations


def _register_class_group(bpy, group) -> None:
    """Register current classes, replacing stale classes left by a reload."""

    for cls in group:
        registered = getattr(bpy.types, cls.__name__, None)
        if registered is cls:
            continue
        if registered is not None:
            try:
                bpy.utils.unregister_class(registered)
            except (RuntimeError, TypeError) as exc:
                raise RuntimeError(
                    f"Blender has a stale Parametric CAD class "
                    f"{cls.__name__!r}; restart Blender once and enable "
                    "the extension again."
                ) from exc
        bpy.utils.register_class(cls)


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
        transform,
        mcp_service,
    )
    from .blender.ui import panels, tools
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
        transform.CLASSES,
        history.CLASSES,
        mcp_service.CLASSES,
        panels.CLASSES,
    ):
        _register_class_group(bpy, group)
    tools.register()
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
        transform,
        mcp_service,
    )
    from .blender.ui import panels, tools
    from .blender.viewport import sketch_overlay

    adapter.unregister_handlers()
    tools.unregister()
    mcp_service.stop_embedded_service()
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
        transform.CLASSES,
        history.CLASSES,
        mcp_service.CLASSES,
        panels.CLASSES,
    )
    for group in reversed(groups):
        for cls in reversed(group):
            registered = getattr(bpy.types, cls.__name__, None)
            if registered is not None:
                bpy.utils.unregister_class(registered)
    properties.unregister()
