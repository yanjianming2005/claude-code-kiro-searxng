"""Tests for the local KM file-aware MCP bridge."""

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "km_file_mcp.py"
SPEC = importlib.util.spec_from_file_location("km_file_mcp", SCRIPT_PATH)
assert SPEC and SPEC.loader
km_file_mcp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(km_file_mcp)


def test_reads_utf8_file_inside_allowed_root(tmp_path, monkeypatch):
    """The bridge reads complete Unicode content directly from an allowed file."""
    article = tmp_path / "article.md"
    body = "标题\n" + "正文内容。" * 3000
    article.write_text(body, encoding="utf-8")
    monkeypatch.setenv("KM_FILE_ALLOWED_ROOTS", str(tmp_path))

    assert km_file_mcp.read_article_file(str(article)) == body


def test_rejects_file_outside_allowed_roots(tmp_path, monkeypatch):
    """The bridge cannot read arbitrary files outside configured roots."""
    article = tmp_path / "article.md"
    article.write_text("secret", encoding="utf-8")
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("KM_FILE_ALLOWED_ROOTS", str(allowed))

    with pytest.raises(ValueError, match="outside KM_FILE_ALLOWED_ROOTS"):
        km_file_mcp.read_article_file(str(article))


def test_build_update_arguments_replaces_file_path_with_content():
    """Only KM-supported fields are forwarded and file_path is never sent."""
    result = km_file_mcp.build_update_arguments(
        {"id": 2180, "file_path": "/tmp/body.md", "title": "Updated", "markdown": True},
        "complete body",
    )

    assert result == {"id": 2180, "content": "complete body", "title": "Updated", "markdown": True}
    assert "file_path" not in result


def test_transport_tool_is_discoverable():
    """Claude Code receives a short-argument file-aware tool schema."""
    tool = km_file_mcp._tools_list()["tools"][0]

    assert tool["name"] == "update_article_from_file"
    assert tool["inputSchema"]["required"] == ["id", "file_path"]
    assert "large" in tool["description"]


def test_tools_call_returns_mcp_result(monkeypatch):
    """tools/call returns the existing KM result without changing its shape."""
    expected = {"content": [{"type": "text", "text": "updated"}], "isError": False}
    monkeypatch.setattr(km_file_mcp, "call_km_update", lambda arguments: expected)

    response = km_file_mcp.handle_request({
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "update_article_from_file", "arguments": {"id": 2180, "file_path": "/tmp/a.md"}},
    })

    assert response == {"jsonrpc": "2.0", "id": 7, "result": expected}
