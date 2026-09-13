import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from frontier_daily.collectors.github import GitHubCollector
from frontier_daily.http import FetchResult
from frontier_daily.schemas import SourceConfig


def _repository(
    name: str,
    *,
    created_at: str = "2026-08-25T12:00:00Z",
    license_id: str | None = "MIT",
    stars: int = 12,
    forks: int = 3,
    fork: bool = False,
    archived: bool = False,
) -> dict:
    return {
        "full_name": f"example/{name}",
        "html_url": f"https://github.com/example/{name}",
        "description": "A useful agent project for reproducible local inference.",
        "created_at": created_at,
        "pushed_at": created_at,
        "language": "Python",
        "stargazers_count": stars,
        "forks_count": forks,
        "topics": ["agent", "inference"],
        "fork": fork,
        "archived": archived,
        "license": {"spdx_id": license_id} if license_id else None,
    }


def test_github_collector_filters_and_ranks_repositories(monkeypatch):
    source = SourceConfig(
        id="github-ai-open-source",
        name="GitHub AI 开源项目",
        kind="github",
        url=(
            "https://api.github.com/search/repositories"
            "?q=agent+OR+inference&sort=stars&order=desc&per_page=50"
        ),
        tier="community",
        max_items=10,
        fetch_pages=True,
    )
    payload = {
        "items": [
            _repository("popular", stars=100, forks=20),
            _repository("small", stars=4, forks=1),
            _repository("unlicensed", license_id=None),
            {
                **_repository("other-license"),
                "license": {"spdx_id": "NOASSERTION", "name": "Other"},
            },
            _repository("old", created_at="2026-08-20T12:00:00Z"),
            _repository("fork", fork=True),
            _repository("archived", archived=True),
        ]
    }
    captured: list[str] = []

    def fake_fetch(url: str, **_kwargs):
        captured.append(url)
        return FetchResult(
            url=url,
            content=json.dumps(payload).encode("utf-8"),
            content_type="application/json; charset=utf-8",
            status_code=200,
        )

    monkeypatch.setattr("frontier_daily.collectors.github.fetch", fake_fetch)
    since = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)

    items = GitHubCollector().collect(source, since)

    assert [item.url for item in items] == [
        "https://github.com/example/popular",
        "https://github.com/example/small",
    ]
    assert "GitHub 开源仓库：example/popular" in items[0].summary
    assert "许可证：MIT" in items[0].summary
    assert items[0].metadata["repository"]["stars"] == 100
    assert items[0].metadata["repository"]["license"] == "MIT"
    assert items[0].published_at == "2026-08-25T12:00:00+00:00"
    assert parse_qs(urlsplit(captured[0]).query)["q"][0].endswith("created:>=2026-08-23")


def test_github_collector_requires_search_query():
    source = SourceConfig(
        id="github-ai-open-source",
        name="GitHub AI 开源项目",
        kind="github",
        url="https://api.github.com/search/repositories?sort=stars",
        tier="community",
    )

    with pytest.raises(ValueError, match="q 参数"):
        GitHubCollector().collect(source, datetime.now(timezone.utc))
