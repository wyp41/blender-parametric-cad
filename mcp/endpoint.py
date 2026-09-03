"""Discovery helpers for the persistent Blender MCP service."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import tempfile
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows does not provide fcntl.
    fcntl = None


DEFAULT_ENDPOINT_FILE = (
    Path(tempfile.gettempdir()) / "blender_parametric_cad_mcp.json"
)
PROTOCOL_NAME = "blender-parametric-cad"


@contextmanager
def endpoint_lock(value: str | os.PathLike[str] | None = None):
    """Serialize service discovery and explicit in-window service startup."""

    path = endpoint_path(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(f"{path.suffix}.lock")
    with lock_path.open("a+") as lock:
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def endpoint_path(value: str | os.PathLike[str] | None = None) -> Path:
    """Return the shared endpoint path used by the server and Blender add-on."""

    configured = value or os.environ.get("BLENDER_CAD_ENDPOINT_FILE")
    return Path(configured).expanduser() if configured else DEFAULT_ENDPOINT_FILE


def read_endpoint(value: str | os.PathLike[str] | None = None) -> dict[str, Any] | None:
    """Read and validate an endpoint file, returning ``None`` when stale/invalid."""

    path = endpoint_path(value)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    host = str(payload.get("host") or "127.0.0.1")
    token = str(payload.get("token") or "")
    try:
        port = int(payload.get("port"))
    except (TypeError, ValueError):
        return None
    if not host or not token or not 1 <= port <= 65535:
        return None
    if payload.get("protocol") not in {None, PROTOCOL_NAME}:
        return None
    return {
        "protocol": PROTOCOL_NAME,
        "host": host,
        "port": port,
        "token": token,
        "pid": payload.get("pid"),
    }


def endpoint_is_reachable(
    endpoint: dict[str, Any] | None, *, timeout: float = 0.25
) -> bool:
    """Return whether an endpoint accepts its published authentication token."""

    if not isinstance(endpoint, dict):
        return False
    host = str(endpoint.get("host") or "127.0.0.1")
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    try:
        port = int(endpoint["port"])
        token = str(endpoint["token"])
    except (KeyError, TypeError, ValueError):
        return False
    if not host or not token or not 1 <= port <= 65535:
        return False
    connection: socket.socket | None = None
    reader = None
    try:
        connection = socket.create_connection((host, port), timeout=timeout)
        connection.settimeout(timeout)
        reader = connection.makefile("rb")
        line = reader.readline()
        if not line:
            return False
        hello = json.loads(line.decode("utf-8"))
        return (
            isinstance(hello, dict)
            and hello.get("type") == "hello"
            and hello.get("token") == token
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        return False
    finally:
        if reader is not None:
            try:
                reader.close()
            except OSError:
                pass
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


def write_endpoint(
    endpoint: dict[str, Any], value: str | os.PathLike[str] | None = None
) -> Path:
    """Atomically publish a service endpoint for another MCP server process."""

    path = endpoint_path(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "protocol": PROTOCOL_NAME,
        "host": str(endpoint["host"]),
        "port": int(endpoint["port"]),
        "token": str(endpoint["token"]),
        "pid": endpoint.get("pid"),
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)
    return path


def remove_endpoint(
    value: str | os.PathLike[str] | None = None,
    *,
    token: str | None = None,
    pid: int | None = None,
) -> None:
    """Remove an endpoint only when it still belongs to this service."""

    path = endpoint_path(value)
    current = read_endpoint(path)
    if current is None:
        # A caller that supplied ownership data must not remove a malformed or
        # concurrently replaced file that it cannot authenticate.
        if token is not None or pid is not None:
            return
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
        return
    if token is not None and current.get("token") != token:
        return
    if pid is not None and current.get("pid") not in {None, pid}:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass
