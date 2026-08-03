"""Tests for local SearXNG Chinese WebSearch routing."""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from kiro.chinese_search import (
    contains_chinese,
    normalize_searxng_results,
    search_chinese_web,
)


def test_contains_chinese_only_routes_cjk_queries():
    """Chinese queries route locally while Latin-only queries do not."""
    assert contains_chinese("深圳南山区二手房均价") is True
    assert contains_chinese("Zhongshan property price") is False


def test_normalize_searxng_results_deduplicates_and_maps_fields():
    """SearXNG fields are converted to the existing Kiro result contract."""
    payload = {
        "results": [
            {
                "title": "蓝波湾房价",
                "url": "https://example.cn/estate",
                "content": "小区挂牌均价",
                "engines": ["baidu", "360search"],
                "publishedDate": "2026-08-03T10:00:00+00:00",
            },
            {
                "title": "duplicate",
                "url": "https://example.cn/estate",
                "content": "duplicate",
            },
        ]
    }

    results = normalize_searxng_results("蓝波湾", payload)

    assert results["source"] == "searxng"
    assert results["totalResults"] == 1
    assert results["results"][0]["snippet"] == "小区挂牌均价"
    assert results["results"][0]["domain"] == "example.cn"
    assert results["results"][0]["engines"] == ["baidu", "360search"]
    assert isinstance(results["results"][0]["publishedDate"], int)


@pytest.mark.asyncio
async def test_search_chinese_web_calls_local_searxng():
    """The client sends one Chinese-language request to the configured instance."""
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(
        return_value={
            "results": [{"title": "结果", "url": "https://example.cn", "content": "摘要"}]
        }
    )
    get = AsyncMock(return_value=response)
    client = AsyncMock()
    client.__aenter__.return_value.get = get

    with patch("kiro.chinese_search.httpx.AsyncClient", return_value=client) as async_client:
        results = await search_chinese_web("中文查询")

    assert results is not None
    assert results["source"] == "searxng"
    assert async_client.call_args.kwargs["trust_env"] is False
    assert get.call_args.args[0].endswith("/search")
    assert get.call_args.kwargs["params"]["language"] == "zh-CN"


@pytest.mark.asyncio
async def test_search_chinese_web_returns_none_on_network_error():
    """A SearXNG outage signals the caller to use its Kiro fallback."""
    get = AsyncMock(side_effect=httpx.ConnectError("offline"))
    client = AsyncMock()
    client.__aenter__.return_value.get = get

    with patch("kiro.chinese_search.httpx.AsyncClient", return_value=client):
        assert await search_chinese_web("中文查询") is None


@pytest.mark.asyncio
async def test_search_chinese_web_retries_transient_http_error():
    """A transient SearXNG HTTP error is retried before Kiro fallback."""
    failed = Mock()
    failed.raise_for_status = Mock(
        side_effect=httpx.HTTPStatusError(
            "temporary",
            request=Mock(),
            response=Mock(status_code=400),
        )
    )
    succeeded = Mock()
    succeeded.raise_for_status = Mock()
    succeeded.json = Mock(
        return_value={
            "results": [{"title": "结果", "url": "https://example.cn", "content": "摘要"}]
        }
    )
    get = AsyncMock(side_effect=[failed, succeeded])
    client = AsyncMock()
    client.__aenter__.return_value.get = get

    with patch("kiro.chinese_search.httpx.AsyncClient", return_value=client), patch(
        "kiro.chinese_search.asyncio.sleep", AsyncMock()
    ):
        results = await search_chinese_web("中文查询")

    assert results is not None
    assert get.await_count == 2
