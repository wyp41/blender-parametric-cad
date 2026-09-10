"""M9C Blender validation through the same high-level MCP handlers as an AI."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import bpy

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from blender_parametric_cad.mcp.blender_worker import BlenderCadWorker


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    worker = BlenderCadWorker()

    def call(name: str, arguments: dict):
        return worker.handle(name, arguments)

    part_result = call("cad_create_part", {"name": "M9C MCP Plate"})
    part_id = part_result["part"]["id"]
    sketch_result = call(
        "cad_create_sketch", {"part_id": part_id, "name": "Base", "plane": "XY"}
    )
    sketch_id = sketch_result["sketch"]["id"]
    rectangle = call(
        "cad_sketch_add_rectangle",
        {"sketch_id": sketch_id, "x_mm": 0, "y_mm": 0, "width_mm": 80, "height_mm": 50},
    )
    ids = rectangle["entity_ids"]
    for constraint_type, entity_id in (
        ("HORIZONTAL", ids["bottom"]),
        ("HORIZONTAL", ids["top"]),
        ("VERTICAL", ids["left"]),
        ("VERTICAL", ids["right"]),
    ):
        result = call(
            "cad_sketch_add_constraint",
            {
                "sketch_id": sketch_id,
                "constraint_type": constraint_type,
                "entity_refs": [{"entity_id": entity_id}],
            },
        )
        _check(result["ok"] and result["solver_status"] == "SOLVED", "Rectangle constraint failed.")
    width = call(
        "cad_sketch_add_dimension",
        {
            "sketch_id": sketch_id,
            "dimension_type": "LENGTH",
            "entity_refs": [{"entity_id": ids["bottom"]}],
            "value_mm": 80,
        },
    )
    height = call(
        "cad_sketch_add_dimension",
        {
            "sketch_id": sketch_id,
            "dimension_type": "LENGTH",
            "entity_refs": [{"entity_id": ids["left"]}],
            "value_mm": 50,
        },
    )
    _check(width["solver_status"] == "SOLVED" and height["solver_status"] == "SOLVED", "Rectangle dimensions failed.")
    base = call(
        "cad_create_extrude",
        {
            "part_id": part_id,
            "sketch_id": sketch_id,
            "distance_mm": 20,
            "operation": "NEW",
            "depth_mode": "BLIND",
        },
    )
    base_feature_id = base["feature"]["id"]
    updated = call(
        "cad_sketch_update_dimension",
        {"sketch_id": sketch_id, "dimension_id": width["dimension_id"], "value_mm": 100},
    )
    _check(updated["solver_status"] == "SOLVED" and updated["rebuild"]["success"], "Width update did not rebuild.")
    inspected = call("cad_get_sketch", {"sketch_id": sketch_id})
    _check(inspected["solver_status"] == "SOLVED", inspected["solver_message"])
    bottom = next(item for item in inspected["entities"] if item["id"] == ids["bottom"])
    _check(abs(bottom["end_mm"][0] - 100.0) < 0.001, "MCP width dimension did not move the rectangle.")

    hole_sketch_result = call(
        "cad_create_sketch",
        {"part_id": part_id, "name": "Hole", "feature_id": base_feature_id, "role": "END_PLANE"},
    )
    hole_sketch_id = hole_sketch_result["sketch"]["id"]
    circle = call(
        "cad_sketch_add_circle",
        {"sketch_id": hole_sketch_id, "cx_mm": 50, "cy_mm": 25, "diameter_mm": 10},
    )
    diameter = call(
        "cad_sketch_add_dimension",
        {
            "sketch_id": hole_sketch_id,
            "dimension_type": "DIAMETER",
            "entity_refs": [{"entity_id": circle["entity_id"]}],
            "value_mm": 10,
        },
    )
    _check(diameter["solver_status"] == "SOLVED", "Hole diameter dimension failed.")
    remove = call(
        "cad_create_extrude",
        {
            "part_id": part_id,
            "sketch_id": hole_sketch_id,
            "distance_mm": 0,
            "operation": "REMOVE",
            "depth_mode": "THROUGH_ALL",
        },
    )
    _check(remove["rebuild"]["success"], "Through-All remove failed.")
    edges = call("cad_get_edges", {"part_id": part_id})["edges"]
    _check(edges, "MCP edge inspection returned no semantic edges.")
    chamfer = call(
        "cad_create_chamfer",
        {"part_id": part_id, "edge_references": [edges[0]["reference"]], "distance_mm": 2},
    )
    _check(chamfer["rebuild"]["success"], "MCP Chamfer failed.")
    history = call("cad_get_history", {"part_id": part_id})
    _check(all(item["status"] == "OK" for item in history["features"]), "MCP history contains a failed feature.")
    validation = call("cad_validate_document", {})
    _check(validation["valid"], json.dumps(validation, ensure_ascii=False))
    raw = call("cad_status", {})["document"]
    _check("mesh_edge_index" not in json.dumps(raw) and "edge_index" not in json.dumps(raw), "Mesh index leaked into CAD JSON.")
    path = str(Path(tempfile.gettempdir()) / "blender_parametric_cad_m9c.blend")
    call("cad_save_scene", {"filepath": path})
    print(f"M9C MCP rectangle + end-to-end CAD: OK ({path})")
    print("BLENDER_PARAMETRIC_CAD_M9C_VALIDATION_OK")


main()
