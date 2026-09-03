"""Operators for hosting the CAD MCP service in the current Blender window."""

from __future__ import annotations

import errno

import bpy

from ...mcp.blender_worker import (
    start_embedded_service,
    stop_embedded_service,
)


class PARAMETRIC_CAD_OT_start_mcp_service(bpy.types.Operator):
    bl_idname = "parametric_cad.start_mcp_service"
    bl_label = "Start CAD MCP Service"
    bl_description = "Let MCP clients edit this open Blender window"
    bl_options = {"REGISTER"}

    def execute(self, context):
        ui = getattr(context.scene, "parametric_cad_ui", None)
        port = int(getattr(ui, "mcp_service_port", 9800))
        try:
            info = start_embedded_service(port=port)
        except (OSError, RuntimeError, ValueError) as exc:
            if isinstance(exc, OSError) and exc.errno == errno.EADDRINUSE:
                message = (
                    f"Port {port} is already in use. Stop the existing CAD MCP "
                    "service or choose another port; no new Blender window was "
                    "started."
                )
            else:
                message = str(exc)
            self.report({"ERROR"}, f"Could not start CAD MCP Service: {message}")
            return {"CANCELLED"}
        context.scene["parametric_cad_mcp_service"] = True
        context.scene["parametric_cad_mcp_endpoint"] = info["endpoint_file"]
        context.scene["parametric_cad_mcp_port"] = int(info["port"])
        self.report(
            {"INFO"},
            f"CAD MCP Service listening on {info['host']}:{info['port']}",
        )
        return {"FINISHED"}


class PARAMETRIC_CAD_OT_stop_mcp_service(bpy.types.Operator):
    bl_idname = "parametric_cad.stop_mcp_service"
    bl_label = "Stop CAD MCP Service"
    bl_description = "Stop the CAD MCP service hosted by this Blender window"
    bl_options = {"REGISTER"}

    def execute(self, context):
        stop_embedded_service()
        context.scene["parametric_cad_mcp_service"] = False
        self.report({"INFO"}, "CAD MCP Service stopped.")
        return {"FINISHED"}


CLASSES = (
    PARAMETRIC_CAD_OT_start_mcp_service,
    PARAMETRIC_CAD_OT_stop_mcp_service,
)
