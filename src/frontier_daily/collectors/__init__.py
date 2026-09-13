from __future__ import annotations

from frontier_daily.schemas import SourceConfig

from .feed import FeedCollector
from .fixture import FixtureCollector
from .github import GitHubCollector
from .sitemap import SitemapCollector


def get_collector(source: SourceConfig):
    if source.kind in {"rss", "atom"}:
        return FeedCollector()
    if source.kind == "sitemap":
        return SitemapCollector()
    if source.kind == "github":
        return GitHubCollector()
    if source.kind == "fixture":
        return FixtureCollector()
    raise ValueError(f"不支持的来源类型：{source.kind}")


__all__ = ["get_collector"]
