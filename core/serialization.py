"""Explicit JSON-compatible serialization for the CAD data model."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from ..features.chamfer import ChamferFeature
from ..features.extrude import ExtrudeFeature
from ..features.fillet import FilletFeature
from ..features.mirror import MirrorFeature
from ..features.revolve import RevolveFeature
from ..features.transform import TransformFeature
from ..sketch.entities import SketchArc, SketchCircle, SketchEntity, SketchLine
from ..sketch.constraints import SketchConstraint, constraint_from_dict, constraint_to_dict
from ..sketch.dimensions import SketchDimension, dimension_from_dict, dimension_to_dict
from ..sketch.plane import DerivedPlaneReference, RegionHint, SketchPlaneReference
from ..sketch.primitives import RectangleDefinition
from ..sketch.sketch import SketchFeature
from .feature import Feature
from .part import Part
from .references import AxisReference, EdgeReference, EdgeSignature, FaceReference


def plane_reference_to_dict(reference: SketchPlaneReference) -> dict[str, Any]:
    data = {
        "reference_type": reference.reference_type,
        "datum_plane": reference.datum_plane,
        "feature_id": reference.feature_id,
        "role": reference.role,
        "source_entity_id": reference.source_entity_id,
        "offset": reference.offset,
        "face_reference": reference.face_reference.to_dict() if reference.face_reference else None,
    }
    if reference.reference_type == "DERIVED_PLANE":
        data.update(
            producer_feature_id=reference.producer_feature_id,
            local_normal=list(reference.local_normal or ()),
            local_offset=reference.local_offset,
            source_feature_ids=list(reference.source_feature_ids),
            region_hint=reference.region_hint.to_dict() if reference.region_hint else None,
        )
    return data


def plane_reference_from_dict(data: dict[str, Any] | None) -> SketchPlaneReference:
    if data is None:
        value: dict[str, Any] = {}
    elif isinstance(data, dict):
        value = data
    else:
        raise ValueError("Plane reference must be a JSON object.")
    reference_type = str(value.get("reference_type", "DATUM"))
    if reference_type == "DERIVED_PLANE":
        return DerivedPlaneReference(
            producer_feature_id=str(
                value.get("producer_feature_id") or value.get("feature_id") or ""
            ),
            local_normal=tuple(float(item) for item in value.get("local_normal", ())),
            local_offset=float(value.get("local_offset")),
            source_feature_ids=tuple(value.get("source_feature_ids", ())),
            region_hint=RegionHint.from_dict(value.get("region_hint")),
            offset=float(value.get("offset", 0.0) or 0.0),
        )
    return SketchPlaneReference(
        reference_type=reference_type,
        datum_plane=value.get("datum_plane"),
        feature_id=value.get("feature_id"),
        role=value.get("role"),
        source_entity_id=value.get("source_entity_id"),
        offset=float(value.get("offset", 0.0) or 0.0),
        face_reference=FaceReference.from_dict(value["face_reference"]) if value.get("face_reference") else None,
    )


def edge_reference_to_dict(reference: EdgeReference) -> dict[str, Any]:
    return {
        "reference_type": reference.reference_type,
        "producer_feature_id": reference.producer_feature_id,
        "role": reference.role,
        "adjacent_plane_refs": [
            plane_reference_to_dict(item) if item is not None else None
            for item in reference.adjacent_plane_refs
        ],
        "source_entity_ids": list(reference.source_entity_ids),
        "local_signature": (
            reference.local_signature.to_dict()
            if reference.local_signature is not None
            else None
        ),
    }


def edge_reference_from_dict(data: dict[str, Any] | None) -> EdgeReference:
    if not isinstance(data, dict):
        raise ValueError("Edge reference must be a JSON object.")
    if "mesh_edge_index" in data or "edge_index" in data:
        raise ValueError("Persistent EdgeReference cannot contain a Blender edge index.")
    planes = list(data.get("adjacent_plane_refs", ()))[:2]
    planes.extend([None] * (2 - len(planes)))
    return EdgeReference(
        producer_feature_id=str(data.get("producer_feature_id") or data.get("feature_id") or ""),
        role=data.get("role"),
        adjacent_plane_refs=tuple(
            plane_reference_from_dict(item) if item else None for item in planes
        ),
        source_entity_ids=tuple(data.get("source_entity_ids", ())),
        local_signature=EdgeSignature.from_dict(data.get("local_signature")),
    )


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
    elif isinstance(entity, SketchArc):
        data.update(
            cx=entity.cx,
            cy=entity.cy,
            radius=entity.radius,
            start_angle=entity.start_angle,
            end_angle=entity.end_angle,
        )
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
    if data["entity_type"] == "ARC":
        return SketchArc(
            **common,
            cx=float(data["cx"]),
            cy=float(data["cy"]),
            radius=float(data["radius"]),
            start_angle=float(data["start_angle"]),
            end_angle=float(data["end_angle"]),
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
            plane_reference=plane_reference_to_dict(feature.plane_reference),
            entities=[entity_to_dict(item) for item in feature.entities],
            deleted_regions=list(feature.deleted_regions),
            dimensions=[dimension_to_dict(item) for item in feature.dimensions],
            constraints=[constraint_to_dict(item) for item in feature.constraints],
            rectangles=[item.to_dict() for item in feature.rectangles],
        )
    elif isinstance(feature, ExtrudeFeature):
        data.update(
            sketch_id=feature.sketch_id,
            distance=feature.distance,
            direction=feature.direction,
            operation=feature.operation,
            depth_mode=feature.depth_mode,
        )
    elif isinstance(feature, RevolveFeature):
        data.update(
            sketch_id=feature.sketch_id,
            axis_reference=feature.axis_reference.to_dict(),
            angle=feature.angle,
            operation=feature.operation,
        )
    elif isinstance(feature, TransformFeature):
        data.update(
            translation=list(feature.translation),
            rotation=list(feature.rotation),
        )
    elif isinstance(feature, MirrorFeature):
        data.update(
            source_feature_id=feature.source_feature_id,
            mirror_plane=plane_reference_to_dict(feature.mirror_plane),
        )
    elif isinstance(feature, ChamferFeature):
        data.update(
            edge_references=[edge_reference_to_dict(item) for item in feature.edge_references],
            distance=feature.distance,
        )
    elif isinstance(feature, FilletFeature):
        data.update(
            edge_references=[edge_reference_to_dict(item) for item in feature.edge_references],
            radius=feature.radius,
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
        return SketchFeature(
            **common,
            plane_reference=plane_reference_from_dict(data.get("plane_reference")),
            entities=[entity_from_dict(item) for item in data.get("entities", [])],
            deleted_regions=list(data.get("deleted_regions", [])),
            dimensions=[dimension_from_dict(item) for item in data.get("dimensions", [])],
            constraints=[constraint_from_dict(item) for item in data.get("constraints", [])],
            rectangles=[RectangleDefinition.from_dict(item) for item in data.get("rectangles", [])],
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
    if data["feature_type"] == "REVOLVE":
        return RevolveFeature(
            **common,
            sketch_id=data["sketch_id"],
            axis_reference=AxisReference.from_dict(data.get("axis_reference", {})),
            angle=float(data.get("angle", 6.283185307179586)),
            operation=data.get("operation", "NEW"),
        )
    if data["feature_type"] == "TRANSFORM":
        translation = tuple(float(value) for value in data.get("translation", (0.0, 0.0, 0.0)))
        rotation = tuple(float(value) for value in data.get("rotation", (0.0, 0.0, 0.0)))
        return TransformFeature(
            **common,
            translation=translation,
            rotation=rotation,
        )
    if data["feature_type"] == "MIRROR":
        return MirrorFeature(
            **common,
            source_feature_id=str(data.get("source_feature_id", "")),
            mirror_plane=plane_reference_from_dict(data.get("mirror_plane")),
        )
    if data["feature_type"] == "CHAMFER":
        return ChamferFeature(
            **common,
            edge_references=[
                edge_reference_from_dict(item)
                for item in data.get("edge_references", [])
            ],
            distance=float(data.get("distance", 0.002)),
        )
    if data["feature_type"] == "FILLET":
        return FilletFeature(
            **common,
            edge_references=[
                edge_reference_from_dict(item)
                for item in data.get("edge_references", [])
            ],
            radius=float(data.get("radius", 0.002)),
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
