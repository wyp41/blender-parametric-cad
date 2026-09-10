"""Small dependency-free MCP protocol surface for the CAD bridge.

The stdio process in :mod:`mcp.server` owns the MCP transport.  Blender runs a
separate, persistent worker process and receives both high-level ``cad_*``
tool calls and trusted direct Python calls; visible sessions keep Blender's
normal event loop active while headless sessions remain available for CI.
Keeping the schemas in this module makes discovery available without starting
Blender and keeps the protocol implementation usable with Python's standard
library only.
"""

from __future__ import annotations

import json
from typing import Any


PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", PROTOCOL_VERSION}
SERVER_NAME = "blender-parametric-cad"
SERVER_VERSION = "0.17.0"


def _object(properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "additionalProperties": False}
    if properties:
        schema["properties"] = properties
    if required:
        schema["required"] = required
    return schema


def _string(description: str, enum: list[str] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"type": "string", "description": description}
    if enum:
        value["enum"] = enum
    return value


def _number(description: str) -> dict[str, Any]:
    return {"type": "number", "description": description}


def _integer(description: str) -> dict[str, Any]:
    return {"type": "integer", "description": description}


_PART_ID = _string("Part Studio UUID. Omit to use the active Part Studio.")
_SKETCH_ID = _string("Sketch feature UUID.")
_FEATURE_ID = _string("Feature UUID.")
_SKETCH_REF = {
    "type": "object",
    "description": "Persistent Sketch reference. sketch_id may be omitted inside its Sketch.",
    "additionalProperties": False,
    "properties": {
        "sketch_id": _SKETCH_ID,
        "entity_id": _string("Sketch entity UUID."),
        "sub_element": _string("ENTITY, START, END, or CENTER.", ["ENTITY", "START", "END", "CENTER"]),
    },
    "required": ["entity_id"],
}
_SKETCH_REF_ARRAY = {
    "type": "array",
    "items": _SKETCH_REF,
    "minItems": 1,
}
_CONSTRAINT_TYPE = _string(
    "Basic Sketch constraint type.",
    ["COINCIDENT", "HORIZONTAL", "VERTICAL", "PARALLEL", "PERPENDICULAR", "EQUAL"],
)
_DIMENSION_TYPE = _string(
    "Driving Sketch dimension type.",
    ["LENGTH", "HORIZONTAL_DISTANCE", "VERTICAL_DISTANCE", "DISTANCE", "RADIUS", "DIAMETER"],
)
_VECTOR3 = {
    "type": "object",
    "description": "Object with numeric x, y, and z fields.",
    "additionalProperties": False,
    "properties": {"x": _number("X value."), "y": _number("Y value."), "z": _number("Z value.")},
}
_MIRROR_PLANE = {
    "description": "Datum plane string or semantic plane object.",
    "oneOf": [
        {"type": "string", "enum": ["XY", "XZ", "YZ"]},
        {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "type": _string("Plane reference type.", ["DATUM", "FEATURE_PLANE", "FACE"]),
                "plane": _string("Datum plane.", ["XY", "XZ", "YZ"]),
                "datum_plane": _string("Datum plane.", ["XY", "XZ", "YZ"]),
                "feature_id": _FEATURE_ID,
                "role": _string("Semantic plane/face role."),
                "source_entity_id": _string("Optional source SketchLine UUID."),
                "offset_mm": _number("Offset along the plane normal in millimeters."),
            },
        },
    ],
}


TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "blender_execute_python",
        "description": (
            "Execute trusted multiline Python in the connected Blender process "
            "on Blender's main thread, equivalent to running code in Blender's "
            "Python Console without Computer Use. The namespace persists between "
            "calls. Use bpy for Blender API access. Returns captured stdout, "
            "stderr, and the repr of a final expression. Full Python access can "
            "modify the current scene, files, and process; use only with a "
            "trusted MCP client."
        ),
        "inputSchema": _object(
            {"code": _string("Python code to execute. Multiline code is supported.")},
            ["code"],
        ),
    },
    {
        "name": "cad_status",
        "description": "Return the persistent CAD document, Part Studios, feature history, and active selection.",
        "inputSchema": _object(),
    },
    {
        "name": "cad_create_part",
        "description": "Create an empty Part Studio and make it active.",
        "inputSchema": _object(
            {"name": _string("Optional Part Studio display name.")}
        ),
    },
    {
        "name": "cad_set_active_part",
        "description": "Make an existing Part Studio active.",
        "inputSchema": _object({"part_id": _PART_ID}, ["part_id"]),
    },
    {
        "name": "cad_delete_part",
        "description": "Delete a Part Studio, its feature history, and generated result mesh.",
        "inputSchema": _object({"part_id": _PART_ID}, ["part_id"]),
    },
    {
        "name": "cad_create_sketch",
        "description": "Create a persistent Sketch on a datum plane, Extrude END_PLANE, or supported face reference.",
        "inputSchema": _object(
            {
                "name": _string("Sketch display name."),
                "part_id": _PART_ID,
                "plane": _string("Datum plane when no feature/face support is supplied.", ["XY", "XZ", "YZ"]),
                "feature_id": _string("Optional source NEW Extrude UUID for an END_PLANE support."),
                "role": _string("Feature support role; currently END_PLANE.", ["END_PLANE"]),
                "offset_mm": _number("Offset along the resolved plane normal in millimeters."),
                "face_reference": {
                    "type": "object",
                    "description": "Optional TopoReference JSON: feature_id, role, and optional source_entity_id.",
                },
            },
            ["name"],
        ),
    },
    {
        "name": "cad_add_geometry",
        "description": "Append a line, circle, arc, or rectangle to a Sketch. Lengths are millimeters; arc angles are degrees.",
        "inputSchema": _object(
            {
                "sketch_id": _SKETCH_ID,
                "geometry": {
                    "type": "object",
                    "description": (
                        "Geometry object. line: type,line x1_mm,y1_mm,x2_mm,y2_mm; "
                        "circle: type,cx_mm,cy_mm,diameter_mm; "
                        "arc: type,cx_mm,cy_mm,radius_mm,start_deg,end_deg; "
                        "rectangle: type,x_mm,y_mm,width_mm,height_mm."
                    ),
                    "additionalProperties": True,
                },
            },
            ["sketch_id", "geometry"],
        ),
    },
    {
        "name": "cad_sketch_add_line",
        "description": "Create one SketchLine and return its stable UUID. Coordinates are Sketch-local millimeters.",
        "inputSchema": _object(
            {
                "sketch_id": _SKETCH_ID,
                "x1_mm": _number("Start U coordinate in millimeters."),
                "y1_mm": _number("Start V coordinate in millimeters."),
                "x2_mm": _number("End U coordinate in millimeters."),
                "y2_mm": _number("End V coordinate in millimeters."),
                "construction": {"type": "boolean", "description": "Construction geometry flag."},
            },
            ["sketch_id", "x1_mm", "y1_mm", "x2_mm", "y2_mm"],
        ),
    },
    {
        "name": "cad_sketch_add_circle",
        "description": "Create one SketchCircle and return its stable UUID. Coordinates and radius/diameter are millimeters.",
        "inputSchema": {
            **_object(
                {
                    "sketch_id": _SKETCH_ID,
                    "cx_mm": _number("Center U coordinate in millimeters."),
                    "cy_mm": _number("Center V coordinate in millimeters."),
                    "diameter_mm": _number("Circle diameter in millimeters."),
                    "radius_mm": _number("Circle radius in millimeters."),
                    "construction": {"type": "boolean", "description": "Construction geometry flag."},
                },
                ["sketch_id", "cx_mm", "cy_mm"],
            ),
            "anyOf": [
                {"required": ["diameter_mm"]},
                {"required": ["radius_mm"]},
            ],
        },
    },
    {
        "name": "cad_sketch_add_rectangle",
        "description": "Create one semantic rectangle backed by four ordinary SketchLines, two driving dimensions, and stable UUIDs.",
        "inputSchema": _object(
            {
                "sketch_id": _SKETCH_ID,
                "x_mm": _number("Lower-left U coordinate in millimeters."),
                "y_mm": _number("Lower-left V coordinate in millimeters."),
                "width_mm": _number("Rectangle width in millimeters."),
                "height_mm": _number("Rectangle height in millimeters."),
                "construction": {"type": "boolean", "description": "Construction geometry flag."},
            },
            ["sketch_id", "width_mm", "height_mm"],
        ),
    },
    {
        "name": "cad_sketch_update_rectangle",
        "description": "Update a semantic rectangle by UUID while preserving its four SketchLine UUIDs and downstream references.",
        "inputSchema": _object(
            {
                "sketch_id": _SKETCH_ID,
                "rectangle_id": _string("Persistent rectangle UUID."),
                "x_mm": _number("Lower-left U coordinate in millimeters."),
                "y_mm": _number("Lower-left V coordinate in millimeters."),
                "width_mm": _number("Rectangle width in millimeters."),
                "height_mm": _number("Rectangle height in millimeters."),
            },
            ["sketch_id", "rectangle_id"],
        ),
    },
    {
        "name": "cad_sketch_add_constraint",
        "description": "Add one basic Sketch constraint transactionally and solve the Sketch.",
        "inputSchema": _object(
            {
                "sketch_id": _SKETCH_ID,
                "constraint_type": _CONSTRAINT_TYPE,
                "entity_refs": _SKETCH_REF_ARRAY,
                "constraint_id": _string("Optional caller-supplied constraint UUID."),
                "enabled": {"type": "boolean", "description": "Whether the constraint participates in solving."},
            },
            ["sketch_id", "constraint_type", "entity_refs"],
        ),
    },
    {
        "name": "cad_sketch_delete_constraint",
        "description": "Delete a Sketch constraint by UUID and solve remaining equations.",
        "inputSchema": _object(
            {"sketch_id": _SKETCH_ID, "constraint_id": _string("Constraint UUID.")},
            ["sketch_id", "constraint_id"],
        ),
    },
    {
        "name": "cad_sketch_add_dimension",
        "description": "Add a driving Sketch dimension transactionally. Values are millimeters.",
        "inputSchema": _object(
            {
                "sketch_id": _SKETCH_ID,
                "dimension_type": _DIMENSION_TYPE,
                "entity_refs": _SKETCH_REF_ARRAY,
                "value_mm": _number("Driving dimension value in millimeters."),
                "dimension_id": _string("Optional caller-supplied dimension UUID."),
                "driving": {"type": "boolean", "description": "Whether the dimension drives geometry."},
            },
            ["sketch_id", "dimension_type", "entity_refs", "value_mm"],
        ),
    },
    {
        "name": "cad_sketch_update_dimension",
        "description": "Update a driving Sketch dimension, solve, and rebuild downstream features.",
        "inputSchema": _object(
            {
                "sketch_id": _SKETCH_ID,
                "dimension_id": _string("Dimension UUID."),
                "value_mm": _number("New dimension value in millimeters."),
            },
            ["sketch_id", "dimension_id", "value_mm"],
        ),
    },
    {
        "name": "cad_sketch_delete_dimension",
        "description": "Delete a Sketch dimension by UUID and solve remaining equations.",
        "inputSchema": _object(
            {"sketch_id": _SKETCH_ID, "dimension_id": _string("Dimension UUID.")},
            ["sketch_id", "dimension_id"],
        ),
    },
    {
        "name": "cad_get_sketch",
        "description": "Inspect Sketch-local entities, semantic rectangles, dimensions, constraints, and solver status in millimeters.",
        "inputSchema": _object({"sketch_id": _SKETCH_ID}, ["sketch_id"]),
    },
    {
        "name": "cad_get_history",
        "description": "Inspect one Part Studio's feature UUIDs, types, dependencies, and statuses.",
        "inputSchema": _object({"part_id": _PART_ID}),
    },
    {
        "name": "cad_get_edges",
        "description": "List current semantic straight-edge references without exposing Blender mesh edge indices.",
        "inputSchema": _object({"part_id": _PART_ID}),
    },
    {
        "name": "cad_list_references",
        "description": "List persistent planes, faces, and straight edges for a Part Studio or one feature. Runtime Blender indices are omitted.",
        "inputSchema": _object({"part_id": _PART_ID, "feature_id": _FEATURE_ID}),
    },
    {
        "name": "cad_inspect_geometry",
        "description": "Inspect the generated Part Studio mesh: connected components, bounding box, manifold status, and volume.",
        "inputSchema": _object({"part_id": _PART_ID}),
    },
    {
        "name": "cad_get_document",
        "description": "Return the complete persistent CAD document as JSON.",
        "inputSchema": _object(),
    },
    {
        "name": "cad_get_part_studio",
        "description": "Return one Part Studio and its complete feature history as JSON.",
        "inputSchema": _object({"part_id": _PART_ID}),
    },
    {
        "name": "cad_get_feature",
        "description": "Return one persistent feature, including Sketch primitive metadata when applicable.",
        "inputSchema": _object({"feature_id": _FEATURE_ID}, ["feature_id"]),
    },
    {
        "name": "cad_update_geometry",
        "description": "Update one existing Sketch entity while preserving its UUID. Rectangle, circle, and arc dimensions use millimeters/degrees.",
        "inputSchema": _object(
            {
                "sketch_id": _SKETCH_ID,
                "entity_id": _string("Sketch entity UUID; any one line of a rectangle identifies the rectangle."),
                "geometry": {
                    "type": "object",
                    "description": "Fields for the existing entity, including type and its geometry values.",
                    "additionalProperties": True,
                },
            },
            ["sketch_id", "entity_id", "geometry"],
        ),
    },
    {
        "name": "cad_delete_geometry",
        "description": "Delete one or more individual Sketch entities by UUID.",
        "inputSchema": _object(
            {
                "sketch_id": _SKETCH_ID,
                "entity_ids": {
                    "type": "array",
                    "description": "Entity UUIDs to remove.",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
            },
            ["sketch_id", "entity_ids"],
        ),
    },
    {
        "name": "cad_profile",
        "description": "Validate a Sketch profile and list all bounded regions, including deleted regions.",
        "inputSchema": _object({"sketch_id": _SKETCH_ID}, ["sketch_id"]),
    },
    {
        "name": "cad_delete_region",
        "description": "Mark one bounded Sketch region as deleted without removing its source geometry. Use region_id or zero-based region_index.",
        "inputSchema": _object(
            {
                "sketch_id": _SKETCH_ID,
                "region_id": _string("Stable region UUID derived from boundary entity UUIDs."),
                "region_index": _integer("Zero-based index from cad_profile regions."),
            },
            ["sketch_id"],
        ),
    },
    {
        "name": "cad_restore_region",
        "description": "Restore a previously deleted bounded Sketch region by stable region_id.",
        "inputSchema": _object(
            {"sketch_id": _SKETCH_ID, "region_id": _string("Stable region ID.")},
            ["sketch_id", "region_id"],
        ),
    },
    {
        "name": "cad_create_extrude",
        "description": "Create and rebuild an Extrude feature. Distances are millimeters; operation is NEW, ADD, or REMOVE.",
        "inputSchema": _object(
            {
                "sketch_id": _SKETCH_ID,
                "part_id": _PART_ID,
                "name": _string("Optional feature display name."),
                "distance_mm": _number("Blind extrusion distance in millimeters."),
                "direction": _integer("Extrusion direction, +1 or -1. Defaults to the feature-plane Remove convention."),
                "operation": _string("Boolean operation.", ["NEW", "ADD", "REMOVE"]),
                "depth_mode": _string("BLIND uses distance_mm; THROUGH_ALL spans the current body.", ["BLIND", "THROUGH_ALL"]),
            },
            ["sketch_id", "distance_mm", "operation", "depth_mode"],
        ),
    },
    {
        "name": "cad_create_revolve",
        "description": "Create and rebuild a Revolve feature. Angles are degrees and axis direction can be reversed.",
        "inputSchema": _object(
            {
                "sketch_id": _SKETCH_ID,
                "part_id": _PART_ID,
                "name": _string("Optional feature display name."),
                "angle_deg": _number("Sweep angle in degrees, greater than 0 and no more than 360."),
                "axis": {
                    "description": "Datum axis string X/Y/Z, or {type:'SKETCH_LINE', sketch_id, entity_id}.",
                    "oneOf": [
                        {"type": "string", "enum": ["X", "Y", "Z"]},
                        {"type": "object", "additionalProperties": True},
                    ],
                },
                "axis_reverse": {"type": "boolean", "description": "Reverse the persistent axis direction."},
                "operation": _string("Boolean operation.", ["NEW", "ADD", "REMOVE"]),
            },
            ["sketch_id", "angle_deg", "axis", "operation"],
        ),
    },
    {
        "name": "cad_create_transform",
        "description": "Create a history Transform feature that moves the current single body and downstream reference frame. Translation is millimeters; rotation is degrees.",
        "inputSchema": _object(
            {
                "part_id": _PART_ID,
                "name": _string("Optional feature display name."),
                "translation_mm": _VECTOR3,
                "rotation_deg": _VECTOR3,
            }
        ),
    },
    {
        "name": "cad_create_mirror",
        "description": "Mirror one earlier additive Extrude or Revolve feature across a datum or semantic plane and union it with the current body.",
        "inputSchema": _object(
            {
                "part_id": _PART_ID,
                "name": _string("Optional feature display name."),
                "source_feature_id": _FEATURE_ID,
                "mirror_plane": _MIRROR_PLANE,
            },
            ["source_feature_id", "mirror_plane"],
        ),
    },
    {
        "name": "cad_create_chamfer",
        "description": "Create an equal-distance Chamfer on persistent straight EdgeReferences. Mesh edge indices are not accepted.",
        "inputSchema": _object(
            {
                "part_id": _PART_ID,
                "name": _string("Optional feature display name."),
                "edge_references": {
                    "type": "array",
                    "description": "Persistent EdgeReference objects returned by the CAD selection/history, never Blender edge indices.",
                    "items": {"type": "object", "additionalProperties": True},
                    "minItems": 1,
                },
                "distance_mm": _number("Equal chamfer distance in millimeters."),
            },
            ["edge_references", "distance_mm"],
        ),
    },
    {
        "name": "cad_create_fillet",
        "description": "Create a constant-radius Fillet on persistent straight EdgeReferences. Mesh edge indices are not accepted.",
        "inputSchema": _object(
            {
                "part_id": _PART_ID,
                "name": _string("Optional feature display name."),
                "edge_references": {
                    "type": "array",
                    "description": "Persistent EdgeReference objects returned by the CAD selection/history, never Blender edge indices.",
                    "items": {"type": "object", "additionalProperties": True},
                    "minItems": 1,
                },
                "radius_mm": _number("Constant fillet radius in millimeters."),
            },
            ["edge_references", "radius_mm"],
        ),
    },
    {
        "name": "cad_update_feature",
        "description": "Edit an existing Sketch, Extrude, Revolve, Transform, Mirror, Chamfer, or Fillet feature and rebuild the Part Studio.",
        "inputSchema": _object(
            {
                "feature_id": _FEATURE_ID,
                "name": _string("Optional new display name."),
                "suppressed": {"type": "boolean", "description": "Suppress or unsuppress the feature."},
                "distance_mm": _number(
                    "Extrude blind distance or equal Chamfer distance in millimeters."
                ),
                "direction": _integer("Extrude direction, +1 or -1."),
                "depth_mode": _string("Extrude depth mode.", ["BLIND", "THROUGH_ALL"]),
                "angle_deg": _number("Revolve angle in degrees."),
                "axis": {"description": "Revolve datum axis or SketchLine axis object."},
                "axis_reverse": {"type": "boolean", "description": "Reverse the Revolve axis direction."},
                "operation": _string("Feature operation.", ["NEW", "ADD", "REMOVE"]),
                "offset_mm": _number("Sketch support-plane offset in millimeters."),
                "translation_mm": _VECTOR3,
                "rotation_deg": _VECTOR3,
                "source_feature_id": _FEATURE_ID,
                "mirror_plane": _MIRROR_PLANE,
                "edge_references": {
                    "type": "array",
                    "description": "Persistent EdgeReference objects for Chamfer/Fillet edits.",
                    "items": {"type": "object", "additionalProperties": True},
                },
                "radius_mm": _number("Fillet radius in millimeters."),
            },
            ["feature_id"],
        ),
    },
    {
        "name": "cad_delete_feature",
        "description": "Delete a feature and all UUID-dependent downstream features, then rebuild.",
        "inputSchema": _object({"feature_id": _FEATURE_ID}, ["feature_id"]),
    },
    {
        "name": "cad_suppress_feature",
        "description": "Set the suppression state of a feature and rebuild.",
        "inputSchema": _object(
            {"feature_id": _FEATURE_ID, "suppressed": {"type": "boolean"}},
            ["feature_id", "suppressed"],
        ),
    },
    {
        "name": "cad_rollback",
        "description": "Roll a Part Studio back through the selected feature UUID, or roll forward when feature_id is omitted.",
        "inputSchema": _object({"feature_id": _FEATURE_ID}),
    },
    {
        "name": "cad_rebuild",
        "description": "Evaluate one Part Studio from persistent history and return feature errors/status.",
        "inputSchema": _object({"part_id": _PART_ID}),
    },
    {
        "name": "cad_validate_document",
        "description": "Run read-only document validation for dependencies, Sketches, failed Features, and generated results.",
        "inputSchema": _object(),
    },
    {
        "name": "cad_export_part",
        "description": "Rebuild and export exactly one Part Studio result as STL, OBJ, or PLY.",
        "inputSchema": _object(
            {
                "part_id": _PART_ID,
                "filepath": _string("Output path. The matching extension is added when omitted."),
                "file_format": _string("Mesh format.", ["STL", "OBJ", "PLY"]),
            },
            ["part_id", "filepath", "file_format"],
        ),
    },
    {
        "name": "cad_save_scene",
        "description": "Save the current Blender scene to a .blend file and make it the MCP worker autosave target.",
        "inputSchema": _object({"filepath": _string("Output .blend path; omit to save the current file path.")}),
    },
)


RESOURCE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "uri": "cad://skill/3d-modelling",
        "name": "3d-modelling skill",
        "description": "Instructions for direct Blender Parametric CAD and MCP tool use.",
        "mimeType": "text/markdown",
    },
    {
        "uri": "cad://api-reference",
        "name": "Blender Parametric CAD API reference",
        "description": "Complete public API, schema, units, limitations, and examples.",
        "mimeType": "text/markdown",
    },
)


def text_content(value: Any) -> list[dict[str, str]]:
    """Return an MCP text content block containing compact JSON."""

    return [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)}]
