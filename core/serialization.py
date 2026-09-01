"""Explicit JSON-compatible serialization for the CAD data model."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from ..features.extrude import ExtrudeFeature
from ..sketch.entities import SketchCircle, SketchEntity, SketchLine
from ..sketch.plane import SketchPlaneReference
from ..sketch.sketch import SketchFeature
from .feature import Feature
from .part import Part


def entity_to_dict(entity: SketchEntity) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": entity.id,
        "entity_type": entity.entity_type,
        "construction": entity.construction,
    }
    if isinstance(entity, SketchLine):
        data.update(x1=entity.x1, y1=entity.y1, x2=entity.x2, y2=entity.y2)
    elif isinstance(entity, SketchCircle):
        data.update(cx=entity.cx, cy=entity.cy, radius=entity.radius)
    else:
        raise ValueError(f"Unsupported sketch entity: {entity.entity_type}")
    return data


def entity_from_dict(data: dict[str, Any]) -> SketchEntity:
    common = {
        "id": data["id"],
        "construction": bool(data.get("construction", False)),
    }
    if data["entity_type"] == "LINE":
        return SketchLine(
            **common,
            x1=float(data["x1"]),
            y1=float(data["y1"]),
            x2=float(data["x2"]),
            y2=float(data["y2"]),
        )
    if data["entity_type"] == "CIRCLE":
        return SketchCircle(
            **common,
            cx=float(data["cx"]),
            cy=float(data["cy"]),
            radius=float(data["radius"]),
        )
    raise ValueError(f"Unsupported sketch entity type: {data['entity_type']}")


def feature_to_dict(feature: Feature) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": feature.id,
        "name": feature.name,
        "feature_type": feature.feature_type,
        "suppressed": feature.suppressed,
        "status": feature.status,
        "error_message": feature.error_message,
        "dependencies": list(feature.dependencies),
    }
    if isinstance(feature, SketchFeature):
        data.update(
            plane_reference={
                "reference_type": feature.plane_reference.reference_type,
                "datum_plane": feature.plane_reference.datum_plane,
                "feature_id": feature.plane_reference.feature_id,
                "role": feature.plane_reference.role,
            },
            entities=[entity_to_dict(item) for item in feature.entities],
        )
    elif isinstance(feature, ExtrudeFeature):
        data.update(
            sketch_id=feature.sketch_id,
            distance=feature.distance,
            direction=feature.direction,
            operation=feature.operation,
            depth_mode=feature.depth_mode,
        )
    else:
        raise ValueError(f"Unsupported CAD feature: {feature.feature_type}")
    return data


def feature_from_dict(data: dict[str, Any]) -> Feature:
    common = {
        "id": data["id"],
        "name": data["name"],
        "suppressed": bool(data.get("suppressed", False)),
        "status": data.get("status", "NOT_EVALUATED"),
        "error_message": data.get("error_message", ""),
        "dependencies": list(data.get("dependencies", [])),
    }
    if data["feature_type"] == "SKETCH":
        reference = data["plane_reference"]
        return SketchFeature(
            **common,
            plane_reference=SketchPlaneReference(
                reference_type=reference["reference_type"],
                datum_plane=reference.get("datum_plane"),
                feature_id=reference.get("feature_id"),
                role=reference.get("role"),
            ),
            entities=[entity_from_dict(item) for item in data.get("entities", [])],
        )
    if data["feature_type"] == "EXTRUDE":
        return ExtrudeFeature(
            **common,
            sketch_id=data["sketch_id"],
            distance=float(data["distance"]),
            direction=int(data.get("direction", 1)),
            operation=data.get("operation", "NEW"),
            depth_mode=data.get("depth_mode", "BLIND"),
        )
    raise ValueError(f"Unsupported CAD feature type: {data['feature_type']}")


def document_to_dict(document: "CadDocument") -> dict[str, Any]:
    return {
        "schema_version": 2,
        "active_part_id": document.active_part_id,
        "parts": [
            {
                "id": part.id,
                "name": part.name,
                "rollback_index": part.rollback_index,
                "features": [feature_to_dict(item) for item in part.features],
            }
            for part in document.parts
        ],
    }


def document_from_dict(data: dict[str, Any]) -> "CadDocument":
    from .document import CadDocument

    data = migrate_document_data(data)
    return CadDocument(
        schema_version=2,
        active_part_id=data.get("active_part_id"),
        parts=[
            Part(
                id=part_data["id"],
                name=part_data["name"],
                features=[feature_from_dict(item) for item in part_data.get("features", [])],
                rollback_index=part_data.get("rollback_index"),
            )
            for part_data in data.get("parts", [])
        ],
    )


def migrate_document_data(data: dict[str, Any]) -> dict[str, Any]:
    """Return schema-v2 data while preserving milestone-1 documents."""

    version = int(data.get("schema_version", 1))
    if version not in {1, 2}:
        raise ValueError(f"Unsupported CAD schema version: {version}")
    migrated = deepcopy(data)
    if version == 1:
        for part in migrated.get("parts", []):
            part["rollback_index"] = None
            for feature in part.get("features", []):
                if feature["feature_type"] == "SKETCH":
                    feature["plane_reference"] = {
                        "reference_type": "DATUM",
                        "datum_plane": feature.get("plane_type", "XY"),
                        "feature_id": None,
                        "role": None,
                    }
                    feature["dependencies"] = []
                elif feature["feature_type"] == "EXTRUDE":
                    feature["dependencies"] = [feature["sketch_id"]]
                    feature["depth_mode"] = "BLIND"
        migrated["schema_version"] = 2
    return migrated


def dumps(document: "CadDocument") -> str:
    return json.dumps(document_to_dict(document), separators=(",", ":"), sort_keys=True)


def loads(value: str) -> "CadDocument":
    from .document import CadDocument

    return CadDocument() if not value else document_from_dict(json.loads(value))


from .document import CadDocument  # noqa: E402  (typing/runtime convenience)
