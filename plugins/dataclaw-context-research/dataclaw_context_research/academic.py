"""Academic source providers for context research."""

from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlencode

import httpx


ARXIV_URL = "https://export.arxiv.org/api/query"


async def search_arxiv(
    *,
    query: str,
    limit: int = 10,
    timeout: int = 12,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 25))
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": safe_limit,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_URL}?{urlencode(params)}"
    async with httpx.AsyncClient(headers={"User-Agent": "DataclawContextResearch/0.1"}, timeout=timeout) as client:
        response = await client.get(url)
        response.raise_for_status()
        text = response.text
    return parse_arxiv(text, query=query)


def parse_arxiv(feed_xml: str, *, query: str) -> list[dict[str, Any]]:
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(feed_xml)
    except ET.ParseError:
        return []
    findings = []
    for entry in root.findall("atom:entry", ns):
        title = _text(entry.find("atom:title", ns))
        url = _text(entry.find("atom:id", ns))
        if not title or not url:
            continue
        authors = [_text(a.find("atom:name", ns)) for a in entry.findall("atom:author", ns)]
        findings.append({
            "query": query,
            "source": "arxiv",
            "source_type": "paper",
            "evidence_level": "medium",
            "title": " ".join(title.split()),
            "url": url,
            "snippet": " ".join(_text(entry.find("atom:summary", ns)).split())[:1000],
            "authors": [a for a in authors if a],
            "published_at": _text(entry.find("atom:published", ns)),
            "updated_at_source": _text(entry.find("atom:updated", ns)),
            "tags": ["academic", "preprint"],
            "accepted_for_okf": False,
        })
    return findings


def _text(node: ET.Element | None) -> str:
    return html.unescape(node.text.strip()) if node is not None and node.text else ""
