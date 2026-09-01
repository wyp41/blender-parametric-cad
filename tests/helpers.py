from __future__ import annotations

from blender_parametric_cad.sketch.entities import SketchLine
from blender_parametric_cad.sketch.sketch import SketchFeature


def rectangle_sketch(width: float = 0.080, height: float = 0.050) -> SketchFeature:
    sketch = SketchFeature.on_plane("Sketch001", "XY")
    sketch.entities = [
        SketchLine(x1=0.0, y1=0.0, x2=width, y2=0.0),
        SketchLine(x1=width, y1=0.0, x2=width, y2=height),
        SketchLine(x1=width, y1=height, x2=0.0, y2=height),
        SketchLine(x1=0.0, y1=height, x2=0.0, y2=0.0),
    ]
    return sketch
