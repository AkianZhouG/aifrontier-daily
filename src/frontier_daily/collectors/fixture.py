from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from frontier_daily.schemas import CandidateItem, SourceConfig, utc_now_iso


class FixtureCollector:
    def collect(self, source: SourceConfig, since: datetime) -> list[CandidateItem]:
        path_text = source.url.removeprefix("file://")
        path = Path(path_text).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("测试样例必须是 JSON 数组")
        discovered_at = utc_now_iso()
        items = []
        for value in raw[: source.max_items]:
            if not isinstance(value, dict):
                continue
            items.append(
                CandidateItem(
                    source_id=source.id,
                    source_name=source.name,
                    source_tier=source.tier,
                    title=str(value.get("title", "")),
                    url=str(value.get("url", "")),
                    published_at=value.get("published_at"),
                    discovered_at=str(value.get("discovered_at") or discovered_at),
                    summary=str(value.get("summary", "")),
                    content=str(value.get("content", "")),
                )
            )
        return [item for item in items if item.title and item.url]
