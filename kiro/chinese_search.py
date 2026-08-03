# -*- coding: utf-8 -*-

"""Local SearXNG-backed search for queries containing Chinese characters."""

import asyncio

from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

import httpx
from loguru import logger

from kiro.config import (
    SEARXNG_ENGINES,
    SEARXNG_RETRIES,
    SEARXNG_RESULT_LIMIT,
    SEARXNG_TIMEOUT,
    SEARXNG_URL,
)


def contains_chinese(text: str) -> bool:
    """Return whether *text* contains a CJK unified ideograph."""
    return any(
        "\u3400" <= char <= "\u4dbf"
        or "\u4e00" <= char <= "\u9fff"
        or "\uf900" <= char <= "\ufaff"
        for char in text
    )


def _published_date_ms(value: Any) -> Optional[int]:
    """Convert a SearXNG published date value to milliseconds when possible."""
    if isinstance(value, (int, float)):
        return int(value * 1000) if value < 10_000_000_000 else int(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return int(datetime.fromisoformat(normalized).timestamp() * 1000)
    except ValueError:
        return None


def normalize_searxng_results(query: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Convert SearXNG JSON results to the Kiro MCP web-search result shape."""
    normalized = []
    seen_urls = set()

    for item in payload.get("results", []):
        url = item.get("url")
        if not isinstance(url, str) or not url or url in seen_urls:
            continue

        seen_urls.add(url)
        result = {
            "title": item.get("title") or url,
            "url": url,
            "snippet": item.get("content") or "",
            "domain": urlsplit(url).netloc,
            "engines": item.get("engines") or ([item["engine"]] if item.get("engine") else []),
        }
        published_date = _published_date_ms(item.get("publishedDate"))
        if published_date is not None:
            result["publishedDate"] = published_date
        normalized.append(result)

        if len(normalized) >= SEARXNG_RESULT_LIMIT:
            break

    return {
        "results": normalized,
        "totalResults": len(normalized),
        "query": query,
        "source": "searxng",
    }


async def search_chinese_web(query: str) -> Optional[Dict[str, Any]]:
    """Search local SearXNG and return normalized results, or ``None`` to fall back."""
    endpoint = f"{SEARXNG_URL.rstrip('/')}/search"
    params = {
        "q": query,
        "format": "json",
        "language": "zh-CN",
        "safesearch": "0",
        "engines": SEARXNG_ENGINES,
    }

    try:
        # SearXNG is local (or on the Docker network). Bypass HTTP_PROXY so a
        # VPN used for Kiro cannot intercept and corrupt container-local calls.
        async with httpx.AsyncClient(timeout=SEARXNG_TIMEOUT, trust_env=False) as client:
            response = None
            for attempt in range(SEARXNG_RETRIES + 1):
                try:
                    response = await client.get(endpoint, params=params)
                    response.raise_for_status()
                    break
                except httpx.HTTPError:
                    if attempt >= SEARXNG_RETRIES:
                        raise
                    await asyncio.sleep(0.25 * (attempt + 1))

            if response is None:
                return None
            results = normalize_searxng_results(query, response.json())
            if not results["results"]:
                logger.warning("SearXNG returned no results; falling back to Kiro MCP")
                return None
            logger.info(
                f"Chinese WebSearch via SearXNG returned {results['totalResults']} results"
            )
            return results
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning(f"SearXNG search failed; falling back to Kiro MCP: {exc}")
        return None
