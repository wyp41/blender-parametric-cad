"""Runtime-only polygon provenance for generated display meshes.

The registry is deliberately not written to Blender custom properties or CAD
JSON.  It is rebuilt from the current evaluator result every time a Part is
rebuilt.
"""

from __future__ import annotations

from ...core.references import TopoReference

_PROVENANCE: dict[int, dict[int, TopoReference]] = {}
_CANDIDATES: dict[int, dict] = {}


def set_face_candidates(obj, context):
    from ...sketch.planar_faces import PlanarFaceResolver
    _CANDIDATES[obj.as_pointer()] = PlanarFaceResolver().build_cache(context)


def get_face_candidate(obj, polygon_index):
    obj = getattr(obj, "original", obj)
    return _CANDIDATES.get(obj.as_pointer(), {}).get(polygon_index)


def get_face_candidates(obj):
    obj = getattr(obj, "original", obj)
    return _CANDIDATES.get(obj.as_pointer(), {})


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
        _CANDIDATES.pop(obj.as_pointer(), None)
    except ReferenceError:
        pass
