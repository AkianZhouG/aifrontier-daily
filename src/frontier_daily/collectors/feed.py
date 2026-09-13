from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

from frontier_daily.http import fetch
from frontier_daily.schemas import CandidateItem, SourceConfig, utc_now_iso


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ET.Element, names: set[str]) -> str:
    for child in element:
        if _local_name(child.tag) in names and child.text:
            return child.text.strip()
    return ""


def _parse_date(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _strip_markup(value: str) -> str:
    value = html.unescape(value or "")
    output: list[str] = []
    inside = False
    for char in value:
        if char == "<":
            inside = True
        elif char == ">":
            inside = False
            output.append(" ")
        elif not inside:
            output.append(char)
    return " ".join("".join(output).split())


class FeedCollector:
    def collect(self, source: SourceConfig, since: datetime) -> list[CandidateItem]:
        result = fetch(source.url)
        root = ET.fromstring(result.content)
        entries = [node for node in root.iter() if _local_name(node.tag) in {"entry", "item"}]
        discovered_at = utc_now_iso()
        candidates: list[CandidateItem] = []
        for entry in entries:
            title = _strip_markup(_child_text(entry, {"title"}))
            summary = _strip_markup(_child_text(entry, {"summary", "description", "content"}))
            date_text = _child_text(entry, {"published", "updated", "pubdate", "date"})
            published = _parse_date(date_text)
            if published and published < since.astimezone(timezone.utc):
                continue

            link = _child_text(entry, {"link"})
            if not link:
                for child in entry:
                    if _local_name(child.tag) == "link":
                        href = child.attrib.get("href", "").strip()
                        rel = child.attrib.get("rel", "alternate")
                        if href and rel in {"alternate", ""}:
                            link = href
                            break
            if not link:
                link = _child_text(entry, {"id", "guid"})
            if not title or not link:
                continue
            link = urljoin(result.url, link)
            candidates.append(
                CandidateItem(
                    source_id=source.id,
                    source_name=source.name,
                    source_tier=source.tier,
                    title=title,
                    url=link,
                    published_at=published.isoformat(timespec="seconds") if published else None,
                    discovered_at=discovered_at,
                    summary=summary[:4000],
                )
            )
            if len(candidates) >= source.max_items:
                break
        return candidates
