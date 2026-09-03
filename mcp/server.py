"""Dependency-free stdio MCP server for Blender Parametric CAD.

The process speaking MCP discovers an already-running CAD service before it
starts anything.  If no live service is published, one persistent Blender
worker is started and its endpoint is published for later MCP processes.  A
visible worker services requests through Blender's timer API, so every rebuild
is visible without blocking the UI.  Headless mode is available for CI or
machines without a display.
"""

from __future__ import annotations

import atexit
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from typing import Any, BinaryIO

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows does not provide fcntl.
    fcntl = None

try:  # Running as ``python -m blender_parametric_cad.mcp.server``.
    from .endpoint import endpoint_path, read_endpoint, remove_endpoint
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
    from endpoint import endpoint_path, read_endpoint, remove_endpoint  # type: ignore[no-redef]
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
        visible: bool | None = None,
        gpu_backend: str | None = None,
        host: str | None = None,
        port: int | None = None,
        endpoint_file: str | None = None,
        autostart: bool | None = None,
    ) -> None:
        self.blender_executable = blender_executable
        self.blend_file = blend_file
        self.autosave = autosave
        self.startup_timeout = startup_timeout
        self.visible = self._resolve_visible(visible)
        self.gpu_backend = self._resolve_gpu_backend(gpu_backend)
        self.host = str(host or os.environ.get("BLENDER_CAD_HOST") or "127.0.0.1")
        self.port = self._resolve_port(port)
        self.endpoint_file = endpoint_path(endpoint_file)
        self.autostart = self._resolve_autostart(autostart)
        self._startup_lock_path = self.endpoint_file.with_suffix(
            f"{self.endpoint_file.suffix}.lock"
        )
        self._connection: socket.socket | None = None
        self._reader: BinaryIO | None = None
        self._writer: BinaryIO | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._owns_process = False
        self._token = secrets.token_urlsafe(32)
        self._next_id = 1

    @property
    def started(self) -> bool:
        return self._connection is not None

    def ensure_started(self) -> None:
        if self.started:
            return
        with self._startup_lock():
            if self.started:
                return
            existing = read_endpoint(self.endpoint_file)
            if existing and self._connect_endpoint(existing, timeout=0.75):
                return
            if existing:
                if self._endpoint_process_alive(existing):
                    raise BridgeError(
                        "A Blender CAD service is already running at "
                        f"{existing.get('host')}:{existing.get('port')}, but it did "
                        "not accept a connection. Reconnect to that service or "
                        "stop it from Blender before starting another service."
                    )
                remove_endpoint(
                    self.endpoint_file,
                    token=existing.get("token"),
                )

            if not self.autostart:
                raise BridgeError(
                    "No reachable Blender CAD service was found and autostart is "
                    "disabled. Start CAD MCP Service in the target Blender "
                    "window, or enable autostart for the one-worker fallback."
                )

            if self._port_is_occupied():
                raise BridgeError(
                    f"Blender CAD port {self.host}:{self.port} is already in use, "
                    "but its endpoint could not be authenticated. Start the "
                    "built-in CAD MCP Service in the intended Blender window, "
                    "or choose a different BLENDER_CAD_PORT; no new Blender "
                    "window was started."
                )

            executable = self._resolve_blender_executable()
            worker = Path(__file__).with_name("blender_worker.py")
            self._token = secrets.token_urlsafe(32)
            command = [executable]
            if self.gpu_backend:
                command.extend(("--gpu-backend", self.gpu_backend))
            if not self.visible:
                command.extend(("--background", "--factory-startup"))
            command.extend(
                (
                    "--python",
                    str(worker),
                    "--",
                    "--host",
                    self.host,
                    "--port",
                    str(self.port),
                    "--token",
                    self._token,
                    "--endpoint-file",
                    str(self.endpoint_file),
                )
            )
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
                    start_new_session=self.visible,
                )
                self._owns_process = True
                deadline = time.monotonic() + self.startup_timeout
                requested = {
                    "host": self.host,
                    "port": self.port,
                    "token": self._token,
                }
                while not self.started:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0.0:
                        raise socket.timeout
                    candidates = [read_endpoint(self.endpoint_file), requested]
                    for candidate in candidates:
                        if candidate and self._connect_endpoint(
                            candidate, timeout=min(0.5, remaining)
                        ):
                            return
                    return_code = self._process.poll()
                    if return_code is not None:
                        raise BridgeError(self._startup_failure_message(return_code))
                    time.sleep(min(0.05, remaining))
            except BridgeError:
                self.close(terminate_visible=True)
                raise
            except (OSError, socket.timeout) as exc:
                self.close(terminate_visible=True)
                raise BridgeError(
                    "Could not start or connect to the Blender worker within "
                    f"{self.startup_timeout:g} seconds. Set "
                    "BLENDER_CAD_EXECUTABLE to the Blender 5.1.2 executable, "
                    "or start the CAD MCP Service in an existing Blender window."
                ) from exc

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.ensure_started()
        request_id = self._next_id
        self._next_id += 1
        try:
            self._write_message(
                {
                    "id": request_id,
                    "method": "tool",
                    "name": name,
                    "arguments": arguments or {},
                    "token": self._token,
                }
            )
            response = self._read_message()
        except BridgeError:
            self.close()
            raise
        if response.get("id") != request_id:
            raise BridgeError("Blender worker returned an out-of-order response.")
        if not response.get("ok", False):
            raise BridgeError(str(response.get("error", "Blender worker failed.")))
        return response.get("result")

    def close(self, terminate_visible: bool = False) -> None:
        # A visible worker is a reusable service. Disconnecting the stdio MCP
        # process must not send shutdown, otherwise the next MCP process would
        # be forced to open another Blender window.
        if (
            self._owns_process
            and self._writer is not None
            and (not self.visible or terminate_visible)
        ):
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
        if self._process is not None and (not self.visible or terminate_visible):
            try:
                self._process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self._process.terminate()
                try:
                    self._process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            self._process = None
            self._owns_process = False
        elif self._process is not None and self._process.poll() is not None:
            # Reap a visible worker only after it has already exited or crashed.
            self._process.wait()
            self._process = None
            self._owns_process = False

    @contextmanager
    def _startup_lock(self):
        """Serialize discovery/spawn so two MCP clients cannot spawn windows."""

        self._startup_lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._startup_lock_path.open("a+") as lock:
            if fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _connect_endpoint(self, endpoint: dict[str, Any], timeout: float) -> bool:
        host = str(endpoint.get("host") or self.host)
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        try:
            port = int(endpoint["port"])
            token = str(endpoint["token"])
        except (KeyError, TypeError, ValueError):
            return False

        connection: socket.socket | None = None
        reader = None
        writer = None
        try:
            connection = socket.create_connection((host, port), timeout=timeout)
            connection.settimeout(timeout)
            reader = connection.makefile("rb")
            writer = connection.makefile("wb")
            line = reader.readline()
            if not line:
                raise BridgeError("Blender service closed during authentication.")
            hello = json.loads(line.decode("utf-8"))
            if hello.get("type") != "hello" or hello.get("token") != token:
                raise BridgeError("Blender service authentication failed.")
            connection.settimeout(None)
            self._connection = connection
            self._reader = reader
            self._writer = writer
            self._token = token
            return True
        except (BridgeError, OSError, UnicodeError, json.JSONDecodeError, TypeError):
            for stream in (reader, writer):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass
            return False

    @staticmethod
    def _endpoint_process_alive(endpoint: dict[str, Any]) -> bool:
        """Treat an unresponsive published endpoint as occupied, not stale.

        Refusing to spawn in this case is intentional: a second Blender window
        would hide the real connection problem and violate the single-instance
        contract.  A dead process leaves a stale endpoint that can be replaced.
        """

        try:
            pid = int(endpoint.get("pid"))
        except (TypeError, ValueError):
            return False
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    @staticmethod
    def _resolve_port(value: int | None) -> int:
        configured = value
        if configured is None:
            configured = os.environ.get("BLENDER_CAD_PORT", "9800")
        try:
            port = int(configured)
        except (TypeError, ValueError) as exc:
            raise BridgeError("BLENDER_CAD_PORT must be an integer.") from exc
        if not 1 <= port <= 65535:
            raise BridgeError("BLENDER_CAD_PORT must be between 1 and 65535.")
        return port

    @staticmethod
    def _resolve_autostart(value: bool | None) -> bool:
        if value is not None:
            return bool(value)
        configured = os.environ.get("BLENDER_CAD_AUTOSTART", "1").strip().lower()
        return configured not in {"0", "false", "no", "off"}

    def _port_is_occupied(self) -> bool:
        """Check the requested port before launching a new Blender process."""

        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind((self.host, self.port))
        except OSError:
            return True
        finally:
            probe.close()
        return False

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

    @staticmethod
    def _resolve_visible(value: bool | None) -> bool:
        if value is not None:
            return bool(value)
        headless = os.environ.get("BLENDER_CAD_HEADLESS", "").strip().lower()
        return headless not in {"1", "true", "yes", "on"}

    def _resolve_gpu_backend(self, value: str | None) -> str | None:
        configured = value
        if configured is None:
            configured = os.environ.get("BLENDER_CAD_GPU_BACKEND")
        backend = str(configured or "").strip().lower() or None
        if backend is None and not self.visible and sys.platform == "darwin":
            # Blender 5.1.2 can initialize Metal even for a background worker
            # on affected macOS installations. CAD evaluation does not need a
            # GPU, and OpenGL is the supported software-safe fallback.
            backend = "opengl"
        if backend not in {None, "opengl", "metal", "vulkan"}:
            raise BridgeError(
                "BLENDER_CAD_GPU_BACKEND must be opengl, metal, or vulkan."
            )
        return backend

    def _startup_failure_message(self, return_code: int) -> str:
        detail = f"Blender worker exited during startup (exit code {return_code})."
        if return_code in {-11, 139}:
            detail += (
                " This is a segmentation fault, commonly caused by GPU backend "
                "initialization on macOS. The headless bridge already selects "
                "OpenGL by default; for a visible session set "
                "BLENDER_CAD_GPU_BACKEND=opengl, or start Blender normally "
                "and use the visible MCP mode."
            )
        return detail

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
                        "exports. MCP dimensions are millimeters and degrees. "
                        "The default worker is a visible Blender session; set "
                        "BLENDER_CAD_HEADLESS=1 for background mode."
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
    parser.add_argument(
        "--host",
        default=os.environ.get("BLENDER_CAD_HOST", "127.0.0.1"),
        help="Blender CAD service host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("BLENDER_CAD_PORT", "9800")),
        help="Blender CAD service port (default: 9800)",
    )
    parser.add_argument(
        "--endpoint-file",
        help="Shared endpoint discovery file for a reusable Blender service",
    )
    parser.add_argument(
        "--no-autostart",
        action="store_true",
        help="Require an already-running Blender CAD service",
    )
    parser.add_argument("--blend-file", help="Blend file to open when the worker starts")
    parser.add_argument("--autosave", help="Blend file to save after mutating tool calls")
    parser.add_argument(
        "--gpu-backend",
        choices=("opengl", "metal", "vulkan"),
        help="Force Blender's GPU backend; macOS headless defaults to OpenGL.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--visible",
        action="store_true",
        help="Show a normal Blender window and keep it open after MCP disconnects (default).",
    )
    mode.add_argument(
        "--headless",
        action="store_true",
        help="Run Blender in background mode for CI or machines without a display.",
    )
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
        visible=False if args.headless else True if args.visible else None,
        gpu_backend=args.gpu_backend,
        host=args.host,
        port=args.port,
        endpoint_file=args.endpoint_file,
        autostart=False if args.no_autostart else None,
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
