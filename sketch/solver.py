"""Replaceable sketch-solver boundary for the basic milestone."""

from __future__ import annotations

from dataclasses import dataclass

from .entities import SketchCircle, SketchLine
from .sketch import SketchFeature


@dataclass
class SolverResult:
    success: bool
    message: str = ""


class SketchSolver:
    """Perform basic entity validation until a constraint solver is introduced."""

    def solve(self, sketch: SketchFeature) -> SolverResult:
        for entity in sketch.entities:
            if isinstance(entity, SketchLine):
                if (entity.x1, entity.y1) == (entity.x2, entity.y2):
                    return SolverResult(False, "Sketch contains a zero-length line.")
            elif isinstance(entity, SketchCircle) and entity.radius <= 0.0:
                return SolverResult(False, "Sketch contains a circle with invalid radius.")
        return SolverResult(True)
