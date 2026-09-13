from __future__ import annotations

import fcntl
import json
import math
import os
import re
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from .collectors import get_collector
from .config import AppConfig
from .content import canonicalize_url, fetch_page_content
from .db import Database
from .dedup import content_fingerprint, fallback_event
from .llm import LLMError, PiRunner
from .quality import (
    QUALITY_POLICY_VERSION,
    assess_candidate,
    source_min_event_importance,
)
from .render import build_draft, write_edition
from .schemas import CandidateItem, SourceConfig, utc_now_iso
from .security import validate_public_https_url


STEPS = (
    "discover",
    "fetch",
    "extract",
    "deduplicate",
    "synthesize",
    "render",
    "commit",
)
PROGRESS = {
    "discover": 10,
    "fetch": 28,
    "extract": 48,
    "deduplicate": 65,
    "synthesize": 78,
    "render": 90,
    "commit": 98,
}

STAGE_LABELS = {
    "starting": "启动",
    "discover": "发现",
    "fetch": "抓取",
    "extract": "提取",
    "deduplicate": "去重",
    "synthesize": "综合",
    "render": "生成",
    "commit": "提交",
    "done": "完成",
}
STATUS_LABELS = {
    "running": "运行中",
    "completed": "已完成",
    "failed": "失败",
    "skipped": "已跳过",
    "cancelled": "已取消",
    "queued": "排队中",
    "ready": "已就绪",
    "partial": "部分完成",
}
FOCUS_WEIGHTS = {
    "编程": 8,
    "代码": 8,
    "智能体": 7,
    "代理": 7,
    "agent": 7,
    "coding": 8,
    "技能": 5,
    "插件": 5,
    "记忆": 5,
    "上下文": 5,
    "推理": 4,
    "检索": 4,
    "草稿": 4,
    "评测": 3,
    "部署": 3,
    "software": 3,
    "terminal": 3,
    "开源": 6,
    "github": 3,
    "仓库": 3,
    "repository": 3,
}
FOCUS_SECONDARY_TERMS = {"记忆", "上下文", "推理", "评测", "部署"}
FOCUS_STOP_TERMS = {
    "人工智能",
    "优先关注",
    "过滤泛泛",
    "开发者工作流",
    "开发者",
    "工作流",
    "工具",
    "模型",
    "能力",
    "可复现部署",
}
_GITHUB_VOLATILE_LABELS = {
    "star",
    "stars",
    "fork",
    "forks",
    "watchers",
    "activity",
    "history",
    "latest commit",
}
_GITHUB_VOLATILE_VALUE = re.compile(
    r"^\d+(?:\.\d+)?[km]?\s*(?:stars?|forks?|watching|commits?)?$",
    re.IGNORECASE,
)


def candidate_fingerprint(source: SourceConfig, item: CandidateItem) -> str:
    if source.kind != "github":
        return content_fingerprint(item.title, item.content, item.summary)
    stable_lines: list[str] = []
    skip_volatile_value = False
    for raw_line in (item.content or "").splitlines():
        line = " ".join(raw_line.split())
        lower = line.lower()
        if lower in _GITHUB_VOLATILE_LABELS:
            skip_volatile_value = True
            continue
        if skip_volatile_value and _GITHUB_VOLATILE_VALUE.fullmatch(lower):
            skip_volatile_value = False
            continue
        skip_volatile_value = False
        if _GITHUB_VOLATILE_VALUE.fullmatch(lower) and any(
            word in lower for word in ("star", "fork", "watching", "commit")
        ):
            continue
        stable_lines.append(line)
    repository = item.metadata.get("repository", {})
    stable_summary = ""
    if isinstance(repository, dict):
        stable_summary = json.dumps(
            {
                key: repository.get(key)
                for key in ("full_name", "description", "license", "language", "topics")
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    return content_fingerprint(item.title, "\n".join(stable_lines), stable_summary)


def stage_label(value: str) -> str:
    return STAGE_LABELS.get(value, value)


def status_label(value: str) -> str:
    return STATUS_LABELS.get(value, value)


def focus_score(event: dict, profile: str) -> int:
    if not profile.strip():
        return 0
    text = " ".join(
        str(event.get(key) or "")
        for key in ("entity", "subject", "title_zh", "summary_zh", "why_it_matters_zh")
    ).lower()
    profile_lower = profile.lower()
    score = 0
    strong_match = False
    direct_match = False
    for term, weight in FOCUS_WEIGHTS.items():
        if term.lower() not in profile_lower or term.lower() not in text:
            continue
        score += weight
        if term not in FOCUS_SECONDARY_TERMS:
            strong_match = strong_match or term not in {"检索", "草稿"}
            direct_match = direct_match or term in {"检索", "草稿"}
    for term in re.findall(r"[A-Za-z][A-Za-z0-9+.-]{1,}|[\u4e00-\u9fff]{2,}", profile):
        if term in FOCUS_STOP_TERMS or term in FOCUS_SECONDARY_TERMS:
            continue
        if term.lower() in text:
            score += 2
            strong_match = True
    if not (strong_match or direct_match):
        return 0
    return score


class PipelineError(RuntimeError):
    pass


class RunLogger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, message: str, **data) -> None:
        payload = {
            "time": utc_now_iso(),
            "message": message,
            **data,
        }
        line = json.dumps(payload, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line, flush=True)


@contextmanager
def run_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PipelineError("已有流水线任务占用运行锁") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


class Pipeline:
    def __init__(self, config: AppConfig, db: Database, run_id: str):
        self.config = config
        self.db = db
        self.run_id = run_id
        run = db.get_run(run_id)
        if not run:
            raise PipelineError(f"未找到运行编号：{run_id}")
        self.run = run
        self.run_dir = config.runs_dir / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.logger = RunLogger(Path(run["log_path"]))
        self.llm_failures: list[str] = []
        self._source_config_cache: dict[str, SourceConfig] | None = None
        self.discovery_stats = {"attempted": 0, "succeeded": 0, "failed": 0}

    def _stage(self, name: str, status: str, detail: str = "") -> None:
        self.db.step(self.run_id, name, status, detail)
        fields = {"current_step": name, "progress_pct": PROGRESS.get(name, 0)}
        if status == "failed":
            fields["error"] = detail[:4000]
        self.db.update_run(self.run_id, **fields)
        self.logger.write(f"{stage_label(name)}：{status_label(status)}", detail=detail)

    def _source_configs(self) -> list[SourceConfig]:
        fixture_path = self.run.get("fixture_path")
        if fixture_path:
            fixture = SourceConfig(
                id="fixture",
                name="内置测试样例",
                kind="fixture",
                url=str(Path(fixture_path).expanduser().resolve()),
                tier="official",
                enabled=False,
                max_items=self.config.max_candidates * 2,
                fetch_pages=False,
            )
            self.db.seed_sources([fixture])
            self.db.set_source_enabled("fixture", False)
            return [fixture]
        sources = []
        for row in self.db.list_sources(enabled_only=True):
            if row["kind"] == "fixture":
                continue
            data = dict(row["config"])
            data["enabled"] = row["enabled"]
            sources.append(SourceConfig.model_validate(data))
        return sources

    def _source_config_map(self) -> dict[str, SourceConfig]:
        if getattr(self, "_source_config_cache", None) is None:
            configs: dict[str, SourceConfig] = {}
            for row in self.db.list_sources():
                data = dict(row["config"])
                data["enabled"] = row["enabled"]
                source = SourceConfig.model_validate(data)
                configs[source.id] = source
            self._source_config_cache = configs
        return self._source_config_cache

    def _discover(self) -> list[tuple[SourceConfig, CandidateItem]]:
        lookback = int(self.db.get_setting("lookback_hours", self.config.lookback_hours))
        # A fresh installation needs enough history to seed the event ledger.
        # Normal daily runs stay on the tighter rolling window.
        if not self.run.get("fixture_path") and self.db.dashboard()["counts"]["events"] == 0:
            lookback = max(lookback, 168)
        since = datetime.now(self.config.tz) - timedelta(hours=lookback)
        discovered: list[tuple[SourceConfig, CandidateItem]] = []
        sources = self._source_configs()
        self.discovery_stats = {"attempted": len(sources), "succeeded": 0, "failed": 0}
        per_source_cap = max(4, math.ceil(self.config.max_candidates / max(len(sources), 1)))
        for source in sources:
            try:
                items = get_collector(source).collect(source, since)
                self.db.source_success(source.id)
                self.discovery_stats["succeeded"] += 1
                discovered.extend((source, item) for item in items[:per_source_cap])
                self.logger.write("来源采集完成", source=source.id, count=len(items))
            except Exception as exc:
                self.discovery_stats["failed"] += 1
                self.db.source_failure(source.id, str(exc))
                self.logger.write("来源采集失败", source=source.id, error=str(exc))
        discovered.sort(key=lambda pair: pair[1].published_at or pair[1].discovered_at, reverse=True)
        return discovered[: self.config.max_candidates]

    def _enrich_one(self, source: SourceConfig, item: CandidateItem) -> CandidateItem:
        if source.kind == "fixture" or not source.fetch_pages:
            return item
        try:
            final_url, page = fetch_page_content(item.url, max_chars=self.config.max_fetch_chars)
        except Exception as exc:
            self.logger.write("页面正文提取降级", url=item.url, error=str(exc))
            return item
        item.url = final_url
        if page.get("title"):
            item.title = page["title"]
        if page.get("description") and not item.summary:
            item.summary = page["description"]
        if page.get("published_at") and not item.published_at:
            item.published_at = page["published_at"]
        item.content = page.get("content", "")
        return item

    def _fetch_and_store(
        self, discovered: list[tuple[SourceConfig, CandidateItem]]
    ) -> list[dict]:
        enriched: list[tuple[SourceConfig, CandidateItem]] = []
        with ThreadPoolExecutor(max_workers=min(6, max(1, len(discovered)))) as pool:
            futures = {
                pool.submit(self._enrich_one, source, item): source
                for source, item in discovered
            }
            for future in as_completed(futures):
                source = futures[future]
                try:
                    enriched.append((source, future.result()))
                except Exception as exc:
                    self.logger.write("候选材料补充失败", source=source.id, error=str(exc))

        batch_item_ids: set[int] = set()
        source_seen: dict[str, int] = {}
        source_readable: dict[str, int] = {}
        quality_stats: dict[str, dict[str, int]] = {}
        for source, item in enriched:
            source_seen[source.id] = source_seen.get(source.id, 0) + 1
            stats = quality_stats.setdefault(source.id, {"accepted": 0, "rejected": 0})
            try:
                if source.kind != "fixture":
                    validate_public_https_url(item.url)
                canonical = canonicalize_url(item.url)
                assessment = assess_candidate(source, item)
                item.metadata["quality"] = assessment.as_metadata()
                fingerprint = candidate_fingerprint(source, item)
                item_id, changed = self.db.add_source_item(
                    run_id=self.run_id,
                    source_id=source.id,
                    url=item.url,
                    canonical_url=canonical,
                    title=item.title,
                    published_at=item.published_at,
                    discovered_at=item.discovered_at,
                    summary=item.summary,
                    content=item.content,
                    content_hash=fingerprint,
                    metadata=item.metadata,
                )
                if item_id in batch_item_ids:
                    # The same canonical URL appeared twice in this discovery batch.
                    # Keep the first disposition instead of letting the later copy overwrite it.
                    continue
                batch_item_ids.add(item_id)
                evidence_chars = len((item.summary or "").strip()) + len((item.content or "").strip())
                if source.kind != "fixture" and evidence_chars < 80:
                    self.db.set_run_item_disposition(
                        self.run_id,
                        item_id,
                        "insufficient_content",
                        "来源只提供标题，没有可用的一手正文",
                    )
                    stats["rejected"] += 1
                    continue
                source_readable[source.id] = source_readable.get(source.id, 0) + 1
                if not assessment.accepted:
                    self.db.set_run_item_disposition(
                        self.run_id,
                        item_id,
                        "quality_rejected",
                        assessment.reason(),
                    )
                    stats["rejected"] += 1
                    continue
                stats["accepted"] += 1
                if not changed:
                    self.db.set_run_item_disposition(
                        self.run_id,
                        item_id,
                        "duplicate_exact",
                        "canonical URL already seen with identical content",
                    )
                    continue
                duplicate = self.db.content_duplicate(item_id, fingerprint)
                if duplicate:
                    self.db.set_run_item_disposition(
                        self.run_id,
                        item_id,
                        "duplicate_content",
                        f"same content as source_item:{duplicate['id']}",
                    )
                    continue
            except Exception as exc:
                self.logger.write("候选材料已拒绝", url=item.url, error=str(exc))
        for source_id, seen_count in source_seen.items():
            stats = quality_stats.get(source_id, {"accepted": 0, "rejected": 0})
            self.logger.write(
                "来源质量准入完成",
                source=source_id,
                examined=seen_count,
                accepted=stats["accepted"],
                rejected=stats["rejected"],
            )
            if seen_count and not source_readable.get(source_id):
                self.db.source_failure(
                    source_id,
                    "source index was reachable but no article exposed enough primary-source content",
                )
        rows = self.db.run_source_items(self.run_id, candidates_only=True)
        self.logger.write("候选材料集已准备", count=len(rows), discovered=len(discovered))
        return rows

    def _agent_settings(self) -> dict:
        return {
            "agent_binary": self.db.get_setting("agent_binary", self.config.pi_binary),
            "agent_provider": self.db.get_setting("agent_provider", self.config.pi_provider),
            "agent_model": self.db.get_setting("agent_model", self.config.pi_model),
            "agent_thinking": self.db.get_setting("agent_thinking", self.config.pi_thinking),
        }

    def _focus_profile(self) -> str:
        return str(self.db.get_setting("focus_profile", self.config.focus_profile) or "").strip()

    def _extract_events(self, items: list[dict]) -> tuple[list, bool]:
        no_llm = bool(self.run.get("no_llm")) or not self.config.llm_enabled
        runner = PiRunner(self.config, self.run_dir, agent_settings=self._agent_settings())
        if items and not no_llm:
            try:
                events = runner.extract_events(items, focus_profile=self._focus_profile())
                if events:
                    return events, True
                self.llm_failures.append("Pi 未返回符合条件的事件")
            except LLMError as exc:
                self.llm_failures.append(str(exc))
                self.logger.write("Pi 事件提取降级", error=str(exc))
        return [fallback_event(item, item_id=int(item["id"])) for item in items], False

    def _filter_extracted_events(self, events: list, items: list[dict]) -> tuple[list, int]:
        items_by_id = {int(item["id"]): item for item in items}
        sources = self._source_config_map()
        accepted = []
        rejected = 0
        referenced_item_ids: set[int] = set()
        accepted_item_ids: set[int] = set()
        rejected_item_reasons: dict[int, str] = {}
        for event in events:
            referenced_item_ids.update(event.source_item_ids)
            event_items = [
                items_by_id[item_id]
                for item_id in event.source_item_ids
                if item_id in items_by_id
            ]
            event_sources = [
                sources[item["source_id"]]
                for item in event_items
                if item.get("source_id") in sources
            ]
            if not event_sources:
                rejected += 1
                continue
            threshold = min(source_min_event_importance(source) for source in event_sources)
            if event.importance >= threshold:
                accepted.append(event)
                accepted_item_ids.update(int(item["id"]) for item in event_items)
                continue
            rejected += 1
            reason = f"事件重要度 {event.importance}，低于来源准入线 {threshold}"
            for item in event_items:
                rejected_item_reasons[int(item["id"])] = reason
            self.logger.write(
                "事件质量准入拒绝",
                event_key=event.event_key,
                importance=event.importance,
                threshold=threshold,
            )
        for item_id, reason in rejected_item_reasons.items():
            if item_id not in accepted_item_ids:
                self.db.set_run_item_disposition(
                    self.run_id,
                    item_id,
                    "quality_rejected_event",
                    reason,
                )
        for item_id in items_by_id.keys() - referenced_item_ids:
            self.db.set_run_item_disposition(
                self.run_id,
                item_id,
                "editorial_rejected",
                "模型未识别出达到事件标准的实质性变化",
            )
        return accepted, rejected

    def _event_meets_quality_policy(self, event: dict) -> bool:
        if not hasattr(self.db, "event_source_profiles"):
            return True
        sources = self._source_config_map()
        eligible_sources: list[SourceConfig] = []
        for profile in self.db.event_source_profiles(int(event["id"])):
            source = sources.get(str(profile.get("source_id") or ""))
            if source is None:
                continue
            metadata = profile.get("metadata") or {}
            quality = metadata.get("quality") if isinstance(metadata, dict) else None
            quality = quality if isinstance(quality, dict) else {}
            current_assessment = quality.get("version") == QUALITY_POLICY_VERSION
            if current_assessment and quality.get("accepted") is False:
                continue
            if source.tier in {"community", "media"} and not current_assessment:
                # Community and media items must have passed the current deterministic
                # policy; old items are not grandfathered into a rebuilt edition.
                continue
            eligible_sources.append(source)
        if not eligible_sources:
            return False
        threshold = min(source_min_event_importance(source) for source in eligible_sources)
        return int(event.get("importance") or 0) >= threshold

    def _combine_with_existing_edition(
        self,
        events: list[dict],
        edition_date: str,
        *,
        rebuild_focus: bool = False,
    ) -> list[dict]:
        existing = self.db.edition_for_date(edition_date)
        focus_profile = self._focus_profile()
        if rebuild_focus:
            values = []
            for value in self.db.list_events(limit=300, status="active"):
                item = dict(value)
                item["delta_claims"] = []
                item["decision"] = "related"
                values.append(item)
            relevant_ids = {
                int(value["id"])
                for value in values
                if focus_score(value, focus_profile) > 0
            }
            for value in values:
                if int(value["id"]) in relevant_ids:
                    value["decision"] = "focus"
        else:
            combined: dict[int, dict] = {}
            if existing and existing.get("status") in {"ready", "partial"}:
                for item in existing.get("items", []):
                    value = dict(item)
                    value["decision"] = value.pop("item_type", "new")
                    value["delta_claims"] = []
                    combined[int(value["id"])] = value
            for event in events:
                combined[int(event["id"])] = event
            values = list(combined.values())
        before_quality_gate = len(values)
        values = [value for value in values if self._event_meets_quality_policy(value)]
        quality_rejected = before_quality_gate - len(values)
        if quality_rejected:
            self.logger.write(
                "日报质量准入已过滤事件",
                rejected=quality_rejected,
                retained=len(values),
            )
        values.sort(
            key=lambda item: (
                focus_score(item, focus_profile) * 100 + int(item.get("importance") or 0),
                item.get("last_seen_at") or "",
            ),
            reverse=True,
        )
        max_items = int(self.db.get_setting("max_items", self.config.max_items))
        return values[:max_items]

    def run_pipeline(self) -> dict:
        edition_date = self.run["edition_date"]
        self.db.update_run(
            self.run_id,
            status="running",
            pid=os.getpid(),
            started_at=utc_now_iso(),
            progress_pct=1,
            current_step="starting",
        )
        self.logger.write(
            "流水线已启动",
            run_id=self.run_id,
            edition_date=edition_date,
            model=self.db.get_setting("agent_model", self.config.pi_model),
            focus_profile=self._focus_profile(),
        )
        try:
            with run_lock(self.config.data_dir / "pipeline.lock"):
                self._stage("discover", "running")
                discovered = self._discover()
                if self.discovery_stats["attempted"] and not self.discovery_stats["succeeded"]:
                    detail = (
                        f"{self.discovery_stats['failed']} 个来源全部采集失败，"
                        "已停止生成空日报，请检查网络或来源配置"
                    )
                    self._stage("discover", "failed", detail)
                    raise PipelineError(detail)
                if not self.discovery_stats["attempted"]:
                    detail = "没有启用的来源，已停止生成空日报"
                    self._stage("discover", "failed", detail)
                    raise PipelineError(detail)
                self._stage("discover", "completed", f"发现 {len(discovered)} 条候选材料")

                self._stage("fetch", "running")
                items = self._fetch_and_store(discovered)
                self._stage("fetch", "completed", f"新增 {len(items)} 份来源材料")

                self._stage("extract", "running")
                extracted_raw, extraction_llm = self._extract_events(items)
                extracted, rejected_events = self._filter_extracted_events(extracted_raw, items)
                self._stage(
                    "extract",
                    "completed",
                    f"提取 {len(extracted_raw)} 个事件，质量准入 {len(extracted)} 个，拒绝 {rejected_events} 个",
                )

                self._stage("deduplicate", "running")
                for event in extracted:
                    self.db.upsert_event(self.run_id, event)
                run_events = self.db.run_events(self.run_id)
                rebuild_requested = bool(self.db.get_setting("report_rebuild_requested", False))
                selected = self._combine_with_existing_edition(
                    run_events,
                    edition_date,
                    rebuild_focus=rebuild_requested,
                )
                focus_detail = ""
                if rebuild_requested:
                    focus_count = sum(item["decision"] == "focus" for item in selected)
                    related_count = sum(item["decision"] == "related" for item in selected)
                    focus_detail = f"，关注主题 {focus_count} 条，相关补充 {related_count} 条"
                self._stage(
                    "deduplicate",
                    "completed",
                    f"发现 {len(run_events)} 个新增或更新事件，日报收录 {len(selected)} 条{focus_detail}",
                )

                existing = self.db.edition_for_date(edition_date)
                if (
                    not run_events
                    and not rebuild_requested
                    and existing
                    and existing.get("status") in {"ready", "partial"}
                ):
                    self._stage("synthesize", "skipped", "没有发现实质增量，保留现有日报")
                    self._stage("render", "skipped", "保留现有日报文件")
                    self._stage("commit", "completed", "幂等操作，无需变更")
                    self.db.update_run(
                        self.run_id,
                        status="completed",
                        progress_pct=100,
                        current_step="done",
                        finished_at=utc_now_iso(),
                    )
                    return {"status": "unchanged", "edition": existing}

                self.db.upsert_edition_draft(edition_date)
                self._stage("synthesize", "running")
                synthesis = None
                synthesis_llm = False
                if selected and self.config.llm_enabled and not bool(self.run.get("no_llm")):
                    try:
                        synthesis = PiRunner(
                            self.config,
                            self.run_dir,
                            agent_settings=self._agent_settings(),
                        ).synthesize_edition(
                            edition_date=edition_date,
                            events=selected,
                            focus_profile=self._focus_profile(),
                        )
                        synthesis_llm = True
                    except LLMError as exc:
                        self.llm_failures.append(str(exc))
                        self.logger.write("Pi 日报综合降级", error=str(exc))
                self._stage(
                    "synthesize",
                    "completed",
                    "Pi 综合" if synthesis_llm else "确定性降级摘要",
                )

                self._stage("render", "running")
                draft = build_draft(
                    edition_date=edition_date,
                    events=selected,
                    synthesis=synthesis,
                )
                artifacts = write_edition(self.config.artifacts_dir, draft)
                self._stage("render", "completed", str(artifacts["html"]))

                self._stage("commit", "running")
                used_llm = (extraction_llm or bool(existing and selected)) and (
                    synthesis_llm or not selected
                )
                status = "ready" if used_llm or not selected else "partial"
                if self.config.llm_required_for_ready and not used_llm and selected:
                    raise PipelineError("当前设置要求模型综合成功后才能标记为已就绪，但 Pi 日报综合失败")
                edition_id = self.db.commit_edition(
                    edition_date=edition_date,
                    status=status,
                    title=draft.title,
                    overview=draft.overview,
                    json_path=artifacts["json"],
                    html_path=artifacts["html"],
                    events=selected,
                )
                self._stage(
                    "commit",
                    "completed",
                    f"日报编号={edition_id}，状态={status_label(status)}",
                )
                self.db.set_setting("report_rebuild_requested", False)
                self.db.update_run(
                    self.run_id,
                    status="completed",
                    progress_pct=100,
                    current_step="done",
                    finished_at=utc_now_iso(),
                    error="; ".join(self.llm_failures)[:4000] if self.llm_failures else None,
                )
                self.logger.write("流水线已完成", status=status, edition_id=edition_id)
                return {
                    "status": status,
                    "edition_id": edition_id,
                    "artifacts": {key: str(path) for key, path in artifacts.items()},
                }
        except BaseException as exc:
            error = f"{type(exc).__name__}: {exc}"
            current = self.db.get_run(self.run_id) or {}
            if current.get("status") != "cancelled":
                self.db.update_run(
                    self.run_id,
                    status="failed",
                    finished_at=utc_now_iso(),
                    error=error[:4000],
                )
                self.db.fail_edition(edition_date, error)
            self.logger.write("流水线失败", error=error, traceback=traceback.format_exc()[-8000:])
            raise
