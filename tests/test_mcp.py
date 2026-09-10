"""Pure-Python checks for the dependency-free MCP transport and schemas."""

from __future__ import annotations

from io import BytesIO
import json
import unittest

from blender_parametric_cad.mcp.protocol import (
    RESOURCE_DEFINITIONS,
    SUPPORTED_PROTOCOL_VERSIONS,
    TOOL_DEFINITIONS,
)
from blender_parametric_cad.mcp.server import StdioMcpServer


class _FakeBridge:
    def __init__(self):
        self.calls = []

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        return {"name": name, "arguments": arguments}


class McpProtocolTests(unittest.TestCase):
    def test_tool_and_resource_names_are_unique(self):
        tool_names = [item["name"] for item in TOOL_DEFINITIONS]
        resource_uris = [item["uri"] for item in RESOURCE_DEFINITIONS]
        self.assertEqual(len(tool_names), len(set(tool_names)))
        self.assertEqual(len(resource_uris), len(set(resource_uris)))
        self.assertIn("cad_export_part", tool_names)
        self.assertIn("cad_create_transform", tool_names)
        self.assertIn("cad_create_mirror", tool_names)
        self.assertIn("cad_create_chamfer", tool_names)
        self.assertIn("cad_create_fillet", tool_names)
        self.assertIn("cad_sketch_add_constraint", tool_names)
        self.assertIn("cad_sketch_add_dimension", tool_names)
        self.assertIn("cad_get_sketch", tool_names)
        self.assertIn("cad_get_history", tool_names)
        self.assertIn("cad_get_edges", tool_names)
        self.assertIn("blender_execute_python", tool_names)
        self.assertIn("cad://api-reference", resource_uris)

    def test_m5_tool_schemas_expose_offset_and_history_parameters(self):
        tools = {item["name"]: item for item in TOOL_DEFINITIONS}
        sketch_properties = tools["cad_create_sketch"]["inputSchema"]["properties"]
        self.assertIn("offset_mm", sketch_properties)
        transform_properties = tools["cad_create_transform"]["inputSchema"]["properties"]
        self.assertIn("translation_mm", transform_properties)
        self.assertIn("rotation_deg", transform_properties)
        mirror_properties = tools["cad_create_mirror"]["inputSchema"]["properties"]
        self.assertIn("source_feature_id", mirror_properties)
        self.assertIn("mirror_plane", mirror_properties)
        chamfer_schema = tools["cad_create_chamfer"]["inputSchema"]
        self.assertEqual(chamfer_schema["required"], ["edge_references", "distance_mm"])
        self.assertIn("edge_references", chamfer_schema["properties"])
        fillet_schema = tools["cad_create_fillet"]["inputSchema"]
        self.assertEqual(fillet_schema["required"], ["edge_references", "radius_mm"])
        self.assertIn("edge_references", fillet_schema["properties"])
        update_properties = tools["cad_update_feature"]["inputSchema"]["properties"]
        self.assertIn("offset_mm", update_properties)
        self.assertIn("edge_references", update_properties)
        self.assertIn("radius_mm", update_properties)
        python_schema = tools["blender_execute_python"]["inputSchema"]
        self.assertEqual(python_schema["required"], ["code"])
        self.assertIn("code", python_schema["properties"])

    def test_m9c_schemas_are_machine_chainable(self):
        tools = {item["name"]: item for item in TOOL_DEFINITIONS}
        rectangle = tools["cad_sketch_add_rectangle"]["inputSchema"]
        self.assertIn("width_mm", rectangle["properties"])
        self.assertIn("height_mm", rectangle["properties"])
        circle = tools["cad_sketch_add_circle"]["inputSchema"]
        self.assertEqual(
            circle["anyOf"],
            [{"required": ["diameter_mm"]}, {"required": ["radius_mm"]}],
        )
        constraint = tools["cad_sketch_add_constraint"]["inputSchema"]
        self.assertIn("constraint_type", constraint["properties"])
        self.assertIn("entity_refs", constraint["properties"])
        self.assertIn("COINCIDENT", constraint["properties"]["constraint_type"]["enum"])
        dimension = tools["cad_sketch_add_dimension"]["inputSchema"]
        self.assertIn("value_mm", dimension["properties"])
        self.assertIn("LENGTH", dimension["properties"]["dimension_type"]["enum"])

    def test_initialize_and_tool_list(self):
        server = StdioMcpServer(_FakeBridge())
        initialized = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": next(iter(SUPPORTED_PROTOCOL_VERSIONS))},
            }
        )
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "blender-parametric-cad")
        listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertTrue(listed["result"]["tools"])
        self.assertIn("cad_create_sketch", {item["name"] for item in listed["result"]["tools"]})

    def test_tool_call_wraps_structured_content(self):
        bridge = _FakeBridge()
        server = StdioMcpServer(bridge)
        response = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "cad_status", "arguments": {}},
            }
        )
        value = response["result"]
        self.assertFalse(value["isError"])
        self.assertEqual(value["structuredContent"]["name"], "cad_status")
        self.assertEqual(bridge.calls, [("cad_status", {})])

    def test_stdio_run_ignores_notifications(self):
        server = StdioMcpServer(_FakeBridge())
        incoming = b"\n".join(
            [
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode(),
                json.dumps({"jsonrpc": "2.0", "id": 4, "method": "ping"}).encode(),
            ]
        ) + b"\n"
        output = BytesIO()
        server.run(BytesIO(incoming), output)
        messages = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(messages[0]["id"], 4)
        self.assertEqual(messages[0]["result"], {})


if __name__ == "__main__":
    unittest.main()
