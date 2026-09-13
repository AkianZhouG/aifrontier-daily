from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from frontier_daily.http import fetch
from frontier_daily.schemas import CandidateItem, SourceConfig, utc_now_iso


_CREATED_QUALIFIER = re.compile(r"(?<!\S)created:\S+", re.IGNORECASE)


def _parse_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _search_url(url: str, since: datetime) -> str:
    parts = urlsplit(url)
    parameters = parse_qsl(parts.query, keep_blank_values=True)
    query_index = next(
        (index for index, (key, _value) in enumerate(parameters) if key.lower() == "q"),
        None,
    )
    if query_index is None or not parameters[query_index][1].strip():
        raise ValueError("GitHub 搜索来源必须在 URL 中包含非空 q 参数")

    query = _CREATED_QUALIFIER.sub("", parameters[query_index][1])
    query = " ".join(query.split())
    query = f"{query} created:>={since.astimezone(timezone.utc).date().isoformat()}"
    parameters[query_index] = (parameters[query_index][0], query)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(parameters, doseq=True), parts.fragment)
    )


def _pattern_matches(patterns: list[str], values: list[str]) -> bool:
    if not patterns:
        return True
    haystack = " ".join(values).lower()
    return any(pattern.lower() in haystack for pattern in patterns)


def _license_name(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    spdx_id = str(value.get("spdx_id") or "").strip()
    if not spdx_id or spdx_id.upper() in {"NOASSERTION", "OTHER"}:
        return ""
    return spdx_id


def _as_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _metadata_summary(
    *,
    full_name: str,
    description: str,
    created_at: datetime,
    pushed_at: datetime | None,
    license_name: str,
    language: str,
    stars: int,
    forks: int,
    topics: list[str],
) -> str:
    details = [
        f"GitHub 开源仓库：{full_name}",
        f"创建时间：{created_at.isoformat(timespec='seconds')}",
        f"许可证：{license_name}",
        f"主要语言：{language or '未注明'}",
        f"Stars：{stars}",
        f"Forks：{forks}",
    ]
    if pushed_at:
        details.insert(2, f"最近推送：{pushed_at.isoformat(timespec='seconds')}")
    if topics:
        details.append(f"主题：{', '.join(topics[:12])}")
    if description:
        details.append(f"项目简介：{description}")
    return "；".join(details)


class GitHubCollector:
    """Discover newly-created, licensed repositories through GitHub's public API.

    The repository search endpoint is used only as a discovery index. The pipeline
    subsequently fetches the repository page when ``fetch_pages`` is enabled, so
    the README and repository itself remain the primary evidence for the model.
    """

    def collect(self, source: SourceConfig, since: datetime) -> list[CandidateItem]:
        result = fetch(_search_url(source.url, since))
        try:
            payload = json.loads(result.text())
        except json.JSONDecodeError as exc:
            raise ValueError("GitHub 搜索接口返回的内容不是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("GitHub 搜索接口返回格式无效")
        if payload.get("message") and not isinstance(payload.get("items"), list):
            raise ValueError(f"GitHub 搜索失败：{str(payload['message'])[:500]}")
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise ValueError("GitHub 搜索接口缺少 items 数组")

        cutoff = since.astimezone(timezone.utc)
        discovered_at = utc_now_iso()
        candidates: list[tuple[tuple[int, int, str], CandidateItem]] = []
        for value in raw_items:
            if not isinstance(value, dict):
                continue
            created_at = _parse_timestamp(value.get("created_at"))
            if created_at is None or created_at < cutoff:
                continue
            if value.get("fork") or value.get("archived"):
                continue

            full_name = str(value.get("full_name") or "").strip()
            html_url = str(value.get("html_url") or "").strip()
            if not full_name or not html_url:
                continue
            license_name = _license_name(value.get("license"))
            # A public GitHub repository is not automatically open source. Only
            # repositories with a recognized license are presented as open source.
            if not license_name:
                continue

            description = " ".join(str(value.get("description") or "").split())
            language = str(value.get("language") or "").strip()
            topics = [
                str(topic).strip()
                for topic in (value.get("topics") or [])
                if str(topic).strip()
            ]
            values = [full_name, html_url, description, language, " ".join(topics)]
            if not _pattern_matches(source.include_patterns, values):
                continue
            if source.exclude_patterns and any(
                _pattern_matches([pattern], values) for pattern in source.exclude_patterns
            ):
                continue

            pushed_at = _parse_timestamp(value.get("pushed_at"))
            stars = _as_int(value.get("stargazers_count"))
            forks = _as_int(value.get("forks_count"))
            summary = _metadata_summary(
                full_name=full_name,
                description=description,
                created_at=created_at,
                pushed_at=pushed_at,
                license_name=license_name,
                language=language,
                stars=stars,
                forks=forks,
                topics=topics,
            )
            title = f"GitHub 开源项目：{full_name}"
            owner = value.get("owner") if isinstance(value.get("owner"), dict) else {}
            item = CandidateItem(
                source_id=source.id,
                source_name=source.name,
                source_tier=source.tier,
                title=title,
                url=html_url,
                published_at=created_at.isoformat(timespec="seconds"),
                discovered_at=discovered_at,
                summary=summary[:4000],
                metadata={
                    "repository": {
                        "full_name": full_name,
                        "description": description,
                        "created_at": created_at.isoformat(timespec="seconds"),
                        "pushed_at": pushed_at.isoformat(timespec="seconds") if pushed_at else None,
                        "license": license_name,
                        "language": language,
                        "stars": stars,
                        "forks": forks,
                        "topics": topics[:20],
                        "owner_type": str(owner.get("type") or ""),
                        "size_kb": _as_int(value.get("size")),
                        "open_issues": _as_int(value.get("open_issues_count")),
                    }
                },
            )
            # GitHub normally returns the requested star ordering. Keep a local
            # deterministic order as a guard when the API returns mixed results.
            candidates.append(((stars, forks, created_at.isoformat()), item))

        candidates.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _score, item in candidates[: source.max_items]]
