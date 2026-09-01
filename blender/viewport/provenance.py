"""Runtime-only polygon provenance for generated display meshes.

The registry is deliberately not written to Blender custom properties or CAD
JSON.  It is rebuilt from the current evaluator result every time a Part is
rebuilt.
"""

from __future__ import annotations

from ...core.references import TopoReference

_PROVENANCE: dict[int, dict[int, TopoReference]] = {}


def set_face_provenance(obj, references: dict[int, TopoReference]) -> None:
    _PROVENANCE[obj.as_pointer()] = dict(references)


def get_face_provenance(obj) -> dict[int, TopoReference]:
    try:
        return dict(_PROVENANCE.get(obj.as_pointer(), {}))
    except ReferenceError:
        return {}


def clear_face_provenance(obj) -> None:
    try:
        _PROVENANCE.pop(obj.as_pointer(), None)
    except ReferenceError:
        pass
