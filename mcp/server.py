"""Dependency-free stdio MCP server for Blender Parametric CAD.

The process speaking MCP is deliberately separate from Blender.  On the first
tool call it starts one persistent background Blender worker and proxies all
subsequent calls over a private localhost socket.  This keeps Blender's own
stdout out of the MCP stream and avoids launching Blender once per operation.
"""

from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
from typing import Any, BinaryIO

try:  # Running as ``python -m blender_parametric_cad.mcp.server``.
    from .protocol import (
        PROTOCOL_VERSION,
        RESOURCE_DEFINITIONS,
        SERVER_NAME,
        SERVER_VERSION,
        SUPPORTED_PROTOCOL_VERSIONS,
        TOOL_DEFINITIONS,
        text_content,
    )
except ImportError:  # Running the checked-out file directly from an MCP config.
    from protocol import (  # type: ignore[no-redef]
        PROTOCOL_VERSION,
        RESOURCE_DEFINITIONS,
        SERVER_NAME,
        SERVER_VERSION,
        SUPPORTED_PROTOCOL_VERSIONS,
        TOOL_DEFINITIONS,
        text_content,
    )


class BridgeError(RuntimeError):
    """A recoverable Blender worker or bridge failure."""


class BlenderBridge:
    """Start one Blender worker and proxy newline-delimited JSON requests."""

    def __init__(
        self,
        blender_executable: str | None = None,
        blend_file: str | None = None,
        autosave: str | None = None,
        startup_timeout: float = 60.0,
    ) -> None:
        self.blender_executable = blender_executable
        self.blend_file = blend_file
        self.autosave = autosave
        self.startup_timeout = startup_timeout
        self._listener: socket.socket | None = None
        self._connection: socket.socket | None = None
        self._reader: BinaryIO | None = None
        self._writer: BinaryIO | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._token = secrets.token_urlsafe(32)
        self._next_id = 1

    @property
    def started(self) -> bool:
        return self._connection is not None and self._process is not None

    def ensure_started(self) -> None:
        if self.started:
            return
        executable = self._resolve_blender_executable()
        worker = Path(__file__).with_name("blender_worker.py")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(self.startup_timeout)
        self._listener = listener
        host, port = listener.getsockname()
        command = [
            executable,
            "--background",
            "--factory-startup",
            "--python",
            str(worker),
            "--",
            "--host",
            host,
            "--port",
            str(port),
            "--token",
            self._token,
        ]
        if self.blend_file:
            command.extend(("--blend-file", self.blend_file))
        if self.autosave:
            command.extend(("--autosave", self.autosave))
        try:
            self._process = subprocess.Popen(
                command,
                cwd=str(worker.parent.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            connection, _address = listener.accept()
        except (OSError, socket.timeout) as exc:
            self.close()
            raise BridgeError(
                "Could not start the Blender worker. Set "
                "BLENDER_CAD_EXECUTABLE to the Blender 5.1.2 executable."
            ) from exc
        finally:
            listener.close()
            self._listener = None

        connection.settimeout(None)
        self._connection = connection
        self._reader = connection.makefile("rb")
        self._writer = connection.makefile("wb")
        try:
            hello = self._read_message()
            if hello.get("type") != "hello" or hello.get("token") != self._token:
                raise BridgeError("Blender worker authentication failed.")
        except Exception:
            self.close()
            raise

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.ensure_started()
        request_id = self._next_id
        self._next_id += 1
        self._write_message(
            {
                "id": request_id,
                "method": "tool",
                "name": name,
                "arguments": arguments or {},
                "token": self._token,
            }
        )
        try:
            response = self._read_message()
        except BridgeError:
            self.close()
            raise
        if response.get("id") != request_id:
            raise BridgeError("Blender worker returned an out-of-order response.")
        if not response.get("ok", False):
            raise BridgeError(str(response.get("error", "Blender worker failed.")))
        return response.get("result")

    def close(self) -> None:
        if self._writer is not None:
            try:
                self._write_message(
                    {"id": 0, "method": "shutdown", "token": self._token}
                )
            except (BrokenPipeError, OSError, BridgeError):
                pass
        for stream in (self._reader, self._writer):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        self._reader = None
        self._writer = None
        if self._connection is not None:
            try:
                self._connection.close()
            except OSError:
                pass
        self._connection = None
        if self._process is not None:
            try:
                self._process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self._process.terminate()
                try:
                    self._process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            self._process = None
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
            self._listener = None

    def _resolve_blender_executable(self) -> str:
        configured = self.blender_executable or os.environ.get(
            "BLENDER_CAD_EXECUTABLE"
        )
        candidates = [configured] if configured else []
        candidates.extend(
            item
            for item in (
                shutil.which("blender"),
                "/Applications/Blender.app/Contents/MacOS/Blender",
            )
            if item
        )
        for candidate in candidates:
            if candidate and (Path(candidate).exists() or shutil.which(candidate)):
                return candidate
        raise BridgeError(
            "Blender 5.1.2 was not found. Set BLENDER_CAD_EXECUTABLE to "
            "the Blender executable (for example "
            "/Applications/Blender.app/Contents/MacOS/Blender)."
        )

    def _write_message(self, message: dict[str, Any]) -> None:
        if self._writer is None:
            raise BridgeError("Blender worker is not connected.")
        try:
            self._writer.write(json.dumps(message, ensure_ascii=False).encode("utf-8"))
            self._writer.write(b"\n")
            self._writer.flush()
        except (BrokenPipeError, OSError) as exc:
            raise BridgeError("Blender worker disconnected.") from exc

    def _read_message(self) -> dict[str, Any]:
        if self._reader is None:
            raise BridgeError("Blender worker is not connected.")
        line = self._reader.readline()
        if not line:
            raise BridgeError("Blender worker exited before returning a response.")
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BridgeError("Blender worker returned invalid JSON.") from exc
        if not isinstance(value, dict):
            raise BridgeError("Blender worker returned a non-object response.")
        return value


class StdioMcpServer:
    """Handle the MCP JSON-RPC methods used by modern MCP clients."""

    def __init__(self, bridge: BlenderBridge) -> None:
        self.bridge = bridge
        self.stopping = False

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        if request_id is None:
            self._handle_notification(method, params)
            return None
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
            return self._result(
                request_id,
                {
                    "protocolVersion": version,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                    },
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "instructions": (
                        "Use cad_* tools for persistent Part Studios, sketches, "
                        "features, Transform/Mirror history, rebuilds, and per-Part "
                        "exports. MCP dimensions are millimeters and degrees."
                    ),
                },
            )
        if method == "ping":
            return self._result(request_id, {})
        if method == "tools/list":
            return self._result(request_id, {"tools": list(TOOL_DEFINITIONS)})
        if method == "resources/list":
            return self._result(request_id, {"resources": list(RESOURCE_DEFINITIONS)})
        if method == "resources/read":
            try:
                return self._result(request_id, {"contents": [self._read_resource(params)]})
            except (KeyError, OSError, ValueError) as exc:
                return self._error(request_id, -32602, str(exc))
        if method == "tools/call":
            return self._call_tool(request_id, params)
        if method == "shutdown":
            self.stopping = True
            return self._result(request_id, None)
        return self._error(request_id, -32601, f"Method not found: {method}")

    def run(self, input_stream: BinaryIO, output_stream: BinaryIO) -> None:
        for line in input_stream:
            if not line.strip():
                continue
            try:
                message = json.loads(line.decode("utf-8"))
                if not isinstance(message, dict):
                    raise ValueError("MCP message must be a JSON object.")
                response = self.handle(message)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                response = self._error(None, -32700, str(exc))
            if response is not None:
                output_stream.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))
                output_stream.write(b"\n")
                output_stream.flush()
            if self.stopping:
                break

    def _call_tool(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        known = {item["name"] for item in TOOL_DEFINITIONS}
        if name not in known:
            return self._error(request_id, -32602, f"Unknown tool: {name}")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return self._error(request_id, -32602, "Tool arguments must be an object.")
        try:
            value = self.bridge.call(name, arguments)
            return self._result(
                request_id,
                {"content": text_content(value), "structuredContent": value, "isError": False},
            )
        except (BridgeError, OSError, ValueError, TypeError) as exc:
            error = {"error": str(exc), "tool": name}
            return self._result(
                request_id,
                {"content": text_content(error), "structuredContent": error, "isError": True},
            )

    def _handle_notification(self, method: Any, _params: dict[str, Any]) -> None:
        if method == "exit":
            self.stopping = True

    @staticmethod
    def _result(request_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

    @staticmethod
    def _read_resource(params: dict[str, Any]) -> dict[str, str]:
        uri = params.get("uri")
        root = Path(__file__).resolve().parent.parent
        paths = {
            "cad://skill/3d-modelling": root / "skills" / "3d-modelling" / "SKILL.md",
            "cad://api-reference": root
            / "skills"
            / "3d-modelling"
            / "references"
            / "blender_parametric_cad_api.md",
        }
        if uri not in paths:
            raise KeyError(f"Unknown resource: {uri}")
        return {
            "uri": uri,
            "mimeType": "text/markdown",
            "text": paths[uri].read_text(encoding="utf-8"),
        }


def _parser():
    import argparse

    parser = argparse.ArgumentParser(description="Blender Parametric CAD MCP server")
    parser.add_argument("--blender", help="Path to Blender 5.1.2 executable")
    parser.add_argument("--blend-file", help="Blend file to open when the worker starts")
    parser.add_argument("--autosave", help="Blend file to save after mutating tool calls")
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=float(os.environ.get("BLENDER_CAD_STARTUP_TIMEOUT", "60")),
        help="Seconds to wait for Blender to connect",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    bridge = BlenderBridge(
        blender_executable=args.blender,
        blend_file=args.blend_file or os.environ.get("BLENDER_CAD_FILE"),
        autosave=args.autosave or os.environ.get("BLENDER_CAD_AUTOSAVE"),
        startup_timeout=args.startup_timeout,
    )
    server = StdioMcpServer(bridge)
    atexit.register(bridge.close)
    try:
        server.run(sys.stdin.buffer, sys.stdout.buffer)
    finally:
        bridge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
