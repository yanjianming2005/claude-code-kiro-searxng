#!/usr/bin/env python3
"""Local MCP bridge for sending KM article bodies directly from disk."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SERVER_NAME = "jemy-km-file"
SERVER_VERSION = "1.0.0"
DEFAULT_KM_MCP_URL = "http://127.0.0.1:8766/proxy/km.jemy.me/mcp.php"
DEFAULT_MAX_FILE_BYTES = 10 * 1024 * 1024


def _allowed_roots() -> tuple[Path, ...]:
    """Return resolved directories from which article files may be read."""
    configured = os.getenv("KM_FILE_ALLOWED_ROOTS")
    raw_roots = configured.split(os.pathsep) if configured else ["/tmp", str(Path.home())]
    return tuple(Path(root).expanduser().resolve() for root in raw_roots if root)


def read_article_file(file_path: str) -> str:
    """Read a UTF-8 article after validating its path and size.

    Args:
        file_path: Absolute or user-relative path supplied by the MCP client.

    Returns:
        UTF-8 article content.

    Raises:
        ValueError: If the path is outside allowed roots, invalid, or too large.
    """
    path = Path(file_path).expanduser().resolve()
    if not any(path == root or path.is_relative_to(root) for root in _allowed_roots()):
        raise ValueError(f"File is outside KM_FILE_ALLOWED_ROOTS: {path}")
    if not path.is_file():
        raise ValueError(f"Article file does not exist: {path}")

    max_bytes = int(os.getenv("KM_FILE_MAX_BYTES", str(DEFAULT_MAX_FILE_BYTES)))
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"Article file is too large: {size} bytes (limit {max_bytes})")

    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Article file is not valid UTF-8: {path}") from exc


def build_update_arguments(arguments: Dict[str, Any], content: str) -> Dict[str, Any]:
    """Build arguments for KM's existing update_article tool.

    Args:
        arguments: File-aware tool arguments from Claude Code.
        content: Article body loaded directly from disk.

    Returns:
        Arguments accepted by KM update_article.

    Raises:
        ValueError: If the article ID is invalid.
    """
    article_id = arguments.get("id")
    if not isinstance(article_id, int) or isinstance(article_id, bool) or article_id <= 0:
        raise ValueError("id must be a positive integer")

    result: Dict[str, Any] = {"id": article_id, "content": content}
    for field in ("title", "url", "markdown", "is_original", "is_overseas", "is_top"):
        if field in arguments:
            result[field] = arguments[field]
    return result


def _parse_mcp_response(body: str) -> Dict[str, Any]:
    """Parse either a JSON or SSE-formatted MCP response body."""
    stripped = body.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)

    data_lines = [line[5:].strip() for line in stripped.splitlines() if line.startswith("data:")]
    if not data_lines:
        raise ValueError("KM MCP returned neither JSON nor SSE data")
    return json.loads(data_lines[-1])


def call_km_update(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Call KM update_article with content loaded from a local file."""
    content = read_article_file(str(arguments.get("file_path", "")))
    update_arguments = build_update_arguments(arguments, content)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "update_article", "arguments": update_arguments},
    }
    request = Request(
        os.getenv("KM_MCP_URL", DEFAULT_KM_MCP_URL),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    timeout = float(os.getenv("KM_FILE_REQUEST_TIMEOUT", "120"))
    try:
        with urlopen(request, timeout=timeout) as response:
            remote = _parse_mcp_response(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ValueError(f"KM MCP HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ValueError(f"Cannot connect to KM MCP: {exc.reason}") from exc

    if "error" in remote:
        raise ValueError(f"KM MCP error: {remote['error']}")
    result = remote.get("result")
    if not isinstance(result, dict):
        raise ValueError("KM MCP returned an invalid tools/call result")
    return result


def _tools_list() -> Dict[str, Any]:
    """Return the local file-aware tool definition."""
    return {
        "tools": [{
            "name": "update_article_from_file",
            "description": (
                "Update a KM article by reading its complete body directly from a local UTF-8 file. "
                "Use this instead of update_article whenever the desired body already exists on disk or is large "
                "enough that generating it inline may be unreliable. Only the short id and file_path travel through "
                "the model output; this tool reads the file locally and calls KM update_article."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "minimum": 1, "description": "KM article ID."},
                    "file_path": {"type": "string", "description": "Path to the complete UTF-8 body file."},
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "markdown": {"type": "boolean"},
                    "is_original": {"type": "integer", "enum": [0, 1]},
                    "is_overseas": {"type": "integer", "enum": [0, 1]},
                    "is_top": {"type": "integer", "enum": [0, 1]},
                },
                "required": ["id", "file_path"],
                "additionalProperties": False,
            },
        }]
    }


def handle_request(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Handle one JSON-RPC request from an MCP stdio client."""
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        return None

    try:
        if method == "initialize":
            requested_version = message.get("params", {}).get("protocolVersion", "2025-06-18")
            result = {
                "protocolVersion": requested_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = _tools_list()
        elif method == "tools/call":
            params = message.get("params", {})
            if params.get("name") != "update_article_from_file":
                raise ValueError(f"Unknown tool: {params.get('name')}")
            arguments = params.get("arguments", {})
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be an object")
            result = call_km_update(arguments)
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except (ValueError, OSError) as exc:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": str(exc)}],
                "isError": True,
            },
        }


def main() -> None:
    """Run the newline-delimited JSON-RPC stdio loop."""
    for line in sys.stdin:
        try:
            message = json.loads(line)
            response = handle_request(message)
            if response is not None:
                print(json.dumps(response, ensure_ascii=False), flush=True)
        except (json.JSONDecodeError, TypeError) as exc:
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}), flush=True)


if __name__ == "__main__":
    main()
