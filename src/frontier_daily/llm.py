from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .config import AppConfig
from .localization import clean_chinese_text
from .schemas import EditionSynthesis, ExtractedEvent, ExtractionBatch
from .security import minimal_subprocess_env


class LLMError(RuntimeError):
    pass


def _clean_generated_text(value: str) -> str:
    return clean_chinese_text(value)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise LLMError("模型输出中没有 JSON 对象")
        text = text[start : end + 1]
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"模型返回的 JSON 无效：{exc}") from exc
    if not isinstance(value, dict):
        raise LLMError("模型返回的 JSON 必须是对象")
    return value


class PiRunner:
    def __init__(
        self,
        config: AppConfig,
        run_dir: Path,
        agent_settings: dict[str, Any] | None = None,
    ):
        self.config = config
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        settings = agent_settings or {}
        self.agent_binary = str(settings.get("agent_binary") or config.pi_binary).strip()
        self.agent_provider = str(settings.get("agent_provider") or config.pi_provider).strip()
        self.agent_model = str(settings.get("agent_model") or config.pi_model).strip()
        self.agent_thinking = str(settings.get("agent_thinking") or config.pi_thinking).strip()

    @property
    def resolved_binary(self) -> str | None:
        found = shutil.which(self.agent_binary)
        if found:
            return str(Path(found).resolve())
        candidate = Path(self.agent_binary).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
        return None

    @property
    def available(self) -> bool:
        return self.resolved_binary is not None

    def _run(self, prompt: str, stage: str) -> dict[str, Any]:
        binary = self.resolved_binary
        if not binary:
            raise LLMError(f"未找到本地智能代理工具：{self.agent_binary}")
        prompt_path = self.run_dir / f"agent-{stage}-prompt.md"
        output_path = self.run_dir / f"agent-{stage}-output.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        cmd = [
            binary,
            "--provider",
            self.agent_provider,
            "--model",
            self.agent_model,
            "--thinking",
            self.agent_thinking,
            "--mode",
            "text",
            "--print",
            "--no-session",
            "--no-tools",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-themes",
            "--no-context-files",
            "--no-approve",
        ]
        cmd.extend((f"@{prompt_path}", "只返回要求的 JSON 对象，不要附加其他文字。"))
        try:
            process = subprocess.run(
                cmd,
                cwd=self.config.root,
                env=minimal_subprocess_env(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.config.pi_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LLMError(
                f"本地智能代理运行超过 {self.config.pi_timeout_seconds} 秒，已超时"
            ) from exc
        combined = (process.stdout or "") + (
            "\n[stderr]\n" + process.stderr if process.stderr else ""
        )
        output_path.write_text(combined[-200_000:], encoding="utf-8")
        if process.returncode != 0:
            error = (process.stderr or process.stdout or "未知智能代理错误")[-4000:]
            raise LLMError(f"本地智能代理退出码为 {process.returncode}：{error}")
        return _extract_json(process.stdout or "")

    def extract_events(
        self, items: list[dict[str, Any]], *, focus_profile: str = ""
    ) -> list[ExtractedEvent]:
        template = (self.config.root / "prompts" / "extract_events.md").read_text(encoding="utf-8")
        bundle = []
        allowed_ids = set()
        for item in items:
            item_id = int(item["id"])
            allowed_ids.add(item_id)
            bundle.append(
                {
                    "source_item_id": item_id,
                    "source": item.get("source_name"),
                    "source_tier": item.get("source_tier"),
                    "title": item.get("title"),
                    "url": item.get("canonical_url") or item.get("url"),
                    "published_at": item.get("published_at"),
                    "quality": (item.get("metadata") or {}).get("quality", {}),
                    "repository": (item.get("metadata") or {}).get("repository", {}),
                    "summary": str(item.get("summary") or "")[:1800],
                    "content": str(item.get("content") or "")[:7000],
                }
            )
        prompt = template.replace("{{FOCUS_PROFILE}}", focus_profile or "未指定，按通用人工智能前沿处理")
        prompt = prompt.replace(
            "{{SOURCE_BUNDLE}}", json.dumps(bundle, ensure_ascii=False, indent=2)
        )
        try:
            parsed = ExtractionBatch.model_validate(self._run(prompt, "extract"))
        except ValidationError as exc:
            raise LLMError(f"事件提取结果未通过格式校验：{exc}") from exc

        merged: dict[str, ExtractedEvent] = {}
        for event in parsed.events:
            event.title_zh = _clean_generated_text(event.title_zh)
            event.summary_zh = _clean_generated_text(event.summary_zh)
            event.why_it_matters_zh = _clean_generated_text(event.why_it_matters_zh)
            for claim in event.claims:
                claim.value = _clean_generated_text(claim.value)
            event.source_item_ids = [item_id for item_id in event.source_item_ids if item_id in allowed_ids]
            if not event.source_item_ids:
                continue
            previous = merged.get(event.event_key)
            if previous is None:
                merged[event.event_key] = event
                continue
            previous.source_item_ids = list(
                dict.fromkeys(previous.source_item_ids + event.source_item_ids)
            )
            seen_claims = {(claim.key, claim.value) for claim in previous.claims}
            previous.claims.extend(
                claim for claim in event.claims if (claim.key, claim.value) not in seen_claims
            )
            previous.importance = max(previous.importance, event.importance)
        return list(merged.values())

    def synthesize_edition(
        self, *, edition_date: str, events: list[dict[str, Any]], focus_profile: str = ""
    ) -> EditionSynthesis:
        template = (self.config.root / "prompts" / "write_edition.md").read_text(encoding="utf-8")
        bundle = [
            {
                "event_id": event["id"],
                "item_type": event["decision"],
                "title": event["title_zh"],
                "summary": event["summary_zh"],
                "why_it_matters": event["why_it_matters_zh"],
                "delta_claims": event.get("delta_claims") or [],
                "source": event.get("source_name"),
                "source_url": event.get("source_url"),
                "published_at": event.get("published_at"),
                "importance": event.get("importance"),
                "confidence": event.get("confidence"),
            }
            for event in events
        ]
        prompt = template.replace("{{EDITION_DATE}}", edition_date).replace(
            "{{FOCUS_PROFILE}}", focus_profile or "未指定，按通用人工智能前沿处理"
        ).replace(
            "{{EVENT_BUNDLE}}", json.dumps(bundle, ensure_ascii=False, indent=2)
        )
        try:
            synthesis = EditionSynthesis.model_validate(self._run(prompt, "edition"))
        except ValidationError as exc:
            raise LLMError(f"日报综合结果未通过格式校验：{exc}") from exc
        expected = {int(event["id"]) for event in events}
        actual = {rewrite.event_id for rewrite in synthesis.item_rewrites}
        if actual != expected or len(synthesis.item_rewrites) != len(events):
            raise LLMError(
                f"日报改写编号与事件不一致：预期={sorted(expected)}，实际={sorted(actual)}"
            )
        synthesis.overview = _clean_generated_text(synthesis.overview)
        synthesis.trend_judgment = [_clean_generated_text(value) for value in synthesis.trend_judgment]
        synthesis.caveats = [_clean_generated_text(value) for value in synthesis.caveats]
        for rewrite in synthesis.item_rewrites:
            rewrite.title = _clean_generated_text(rewrite.title)
            rewrite.summary = _clean_generated_text(rewrite.summary)
            rewrite.why_it_matters = _clean_generated_text(rewrite.why_it_matters)
        return synthesis
