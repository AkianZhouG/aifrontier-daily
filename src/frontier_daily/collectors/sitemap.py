from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

from frontier_daily.http import fetch
from frontier_daily.schemas import CandidateItem, SourceConfig, utc_now_iso


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _text(node: ET.Element, name: str) -> str:
    for child in node:
        if _local_name(child.tag) == name and child.text:
            return child.text.strip()
    return ""


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _title_from_url(url: str) -> str:
    path = unquote(urlparse(url).path).strip("/")
    slug = path.rsplit("/", 1)[-1] if path else urlparse(url).hostname or url
    return re.sub(r"[-_]+", " ", slug).strip().title()


class SitemapCollector:
    def _read_urls(self, url: str, depth: int = 0) -> list[tuple[str, str]]:
        if depth > 1:
            return []
        response = fetch(url)
        root = ET.fromstring(response.content)
        root_name = _local_name(root.tag)
        if root_name == "sitemapindex":
            children = []
            for node in root:
                location = _text(node, "loc")
                lastmod = _text(node, "lastmod")
                children.append((location, lastmod))
            children.sort(key=lambda pair: pair[1], reverse=True)
            output: list[tuple[str, str]] = []
            for location, _ in children[:12]:
                if location:
                    output.extend(self._read_urls(location, depth + 1))
            return output
        output = []
        for node in root:
            if _local_name(node.tag) != "url":
                continue
            location = _text(node, "loc")
            if location:
                output.append((location, _text(node, "lastmod")))
        return output

    def collect(self, source: SourceConfig, since: datetime) -> list[CandidateItem]:
        discovered_at = utc_now_iso()
        rows = self._read_urls(source.url)
        filtered: list[tuple[str, datetime | None]] = []
        for url, lastmod in rows:
            if source.include_patterns and not any(pattern in url for pattern in source.include_patterns):
                continue
            if source.exclude_patterns and any(pattern in url for pattern in source.exclude_patterns):
                continue
            parsed = _parse_date(lastmod)
            if parsed and parsed < since.astimezone(timezone.utc):
                continue
            filtered.append((url, parsed))
        filtered.sort(key=lambda pair: pair[1] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return [
            CandidateItem(
                source_id=source.id,
                source_name=source.name,
                source_tier=source.tier,
                title=_title_from_url(url),
                url=url,
                published_at=published.isoformat(timespec="seconds") if published else None,
                discovered_at=discovered_at,
            )
            for url, published in filtered[: source.max_items]
        ]
