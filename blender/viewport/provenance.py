"""Runtime-only polygon provenance for generated display meshes.

The registry is deliberately not written to Blender custom properties or CAD
JSON.  It is rebuilt from the current evaluator result every time a Part is
rebuilt.
"""

from __future__ import annotations

from ...core.references import TopoReference

_PROVENANCE: dict[int, dict[int, TopoReference]] = {}
_CANDIDATES: dict[int, dict] = {}
_EDGE_CANDIDATES: dict[int, dict] = {}


def set_face_candidates(obj, context):
    from ...sketch.planar_faces import PlanarFaceResolver
    _CANDIDATES[obj.as_pointer()] = PlanarFaceResolver().build_cache(context)


def get_face_candidate(obj, polygon_index):
    obj = getattr(obj, "original", obj)
    return _CANDIDATES.get(obj.as_pointer(), {}).get(polygon_index)


def get_face_candidates(obj):
    obj = getattr(obj, "original", obj)
    return _CANDIDATES.get(obj.as_pointer(), {})


def set_edge_candidates(obj, context) -> None:
    from ...sketch.edges import PersistentEdgeResolver

    _EDGE_CANDIDATES[obj.as_pointer()] = PersistentEdgeResolver().build_cache(context)


def get_edge_candidate(obj, mesh_edge_index):
    obj = getattr(obj, "original", obj)
    return _EDGE_CANDIDATES.get(obj.as_pointer(), {}).get(mesh_edge_index)


def get_edge_candidates(obj):
    obj = getattr(obj, "original", obj)
    return _EDGE_CANDIDATES.get(obj.as_pointer(), {})


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
        _EDGE_CANDIDATES.pop(obj.as_pointer(), None)
    except ReferenceError:
        pass
