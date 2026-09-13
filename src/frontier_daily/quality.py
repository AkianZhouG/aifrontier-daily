from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .schemas import CandidateItem, SourceConfig


QUALITY_POLICY_VERSION = 1

_DEFAULT_MIN_SCORES = {
    "official": 50,
    "paper": 60,
    "community": 70,
    "media": 75,
}
_DEFAULT_EVENT_IMPORTANCE = {
    "official": 65,
    "paper": 65,
    "community": 75,
    "media": 80,
}
_TIER_BASE_SCORES = {
    "official": 25,
    "paper": 30,
    "community": 10,
    "media": 5,
}
_PROMOTIONAL_TITLE_PATTERNS = (
    r"\bwebinar\b",
    r"\bregister now\b",
    r"\bjoin (?:our|the) event\b",
    r"\bconference agenda\b",
    r"\bevent invitation\b",
    r"\bnewsletter\b",
    r"\bweekly roundup\b",
    r"\bcareers?\b",
    r"\bwe(?:'|’)re hiring\b",
    r"\bjob openings?\b",
    r"活动报名",
    r"招聘",
    r"职位空缺",
)
_CONCRETE_EVIDENCE = re.compile(
    r"\d|\b(?:api|benchmark|model|dataset|license|security|vulnerability|release|"
    r"repository|code|latency|throughput|parameter|deployment|evaluation)\b|"
    r"基准|许可证|参数|延迟|吞吐|部署|评测|漏洞|代码|开源",
    re.IGNORECASE,
)
_DOCUMENTATION_GROUPS = (
    ("install", "installation", "安装"),
    ("getting started", "quickstart", "quick start", "快速开始"),
    ("usage", "how to use", "用法", "使用方式"),
    ("example", "examples", "demo", "示例"),
    ("test", "tests", "testing", "测试"),
    ("benchmark", "evaluation", "基准", "评测"),
    ("documentation", "docs", "文档"),
    ("license", "许可"),
    ("deploy", "deployment", "部署"),
)


@dataclass(frozen=True)
class QualityAssessment:
    score: int
    threshold: int
    accepted: bool
    signals: tuple[str, ...]
    failures: tuple[str, ...]
    documentation_signals: int = 0

    def as_metadata(self) -> dict[str, Any]:
        return {
            "version": QUALITY_POLICY_VERSION,
            "score": self.score,
            "threshold": self.threshold,
            "accepted": self.accepted,
            "signals": list(self.signals),
            "failures": list(self.failures),
            "documentation_signals": self.documentation_signals,
        }

    def reason(self) -> str:
        details = self.failures or self.signals
        suffix = "；".join(details[:5])
        return f"质量分 {self.score}/{self.threshold}" + (f"；{suffix}" if suffix else "")


def source_min_score(source: SourceConfig) -> int:
    configured = source.quality.min_score
    return configured if configured is not None else _DEFAULT_MIN_SCORES[source.tier]


def source_min_event_importance(source: SourceConfig) -> int:
    configured = source.quality.min_event_importance
    return configured if configured is not None else _DEFAULT_EVENT_IMPORTANCE[source.tier]


def _evidence_score(content_chars: int, summary_chars: int) -> tuple[int, str]:
    if content_chars >= 4_000:
        return 35, f"一手正文 {content_chars} 字符"
    if content_chars >= 1_500:
        return 30, f"一手正文 {content_chars} 字符"
    if content_chars >= 700:
        return 24, f"一手正文 {content_chars} 字符"
    if content_chars >= 300:
        return 16, f"一手正文 {content_chars} 字符"
    if content_chars >= 120:
        return 8, f"一手正文 {content_chars} 字符"
    if summary_chars >= 1_000:
        return 30, f"来源摘要 {summary_chars} 字符"
    if summary_chars >= 500:
        return 25, f"来源摘要 {summary_chars} 字符"
    if summary_chars >= 250:
        return 20, f"来源摘要 {summary_chars} 字符"
    if summary_chars >= 120:
        return 15, f"来源摘要 {summary_chars} 字符"
    if summary_chars >= 60:
        return 8, f"来源摘要 {summary_chars} 字符"
    return 0, "缺少足够的一手正文或摘要"


def _documentation_signal_count(content: str) -> int:
    text = content.lower()
    return sum(1 for group in _DOCUMENTATION_GROUPS if any(term in text for term in group))


def _repository_metadata(item: CandidateItem) -> dict[str, Any]:
    value = item.metadata.get("repository", {})
    return value if isinstance(value, dict) else {}


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def assess_candidate(source: SourceConfig, item: CandidateItem) -> QualityAssessment:
    if source.kind == "fixture":
        return QualityAssessment(
            score=100,
            threshold=0,
            accepted=True,
            signals=("测试样例不参与生产质量筛选",),
            failures=(),
        )

    policy = source.quality
    threshold = source_min_score(source)
    title = " ".join((item.title or "").split())
    summary = " ".join((item.summary or "").split())
    content = (item.content or "").strip()
    content_chars = len(content)
    summary_chars = len(summary)
    combined = f"{title}\n{summary}\n{content}"
    signals: list[str] = []
    failures: list[str] = []
    score = _TIER_BASE_SCORES[source.tier]
    signals.append(f"来源等级：{source.tier}")

    evidence_points, evidence_signal = _evidence_score(content_chars, summary_chars)
    score += evidence_points
    signals.append(evidence_signal)
    if len(title) >= 12:
        score += 5
        signals.append("标题信息完整")
    if item.published_at:
        score += 5
        signals.append("有明确发布时间")
    if _CONCRETE_EVIDENCE.search(combined):
        score += 5
        signals.append("包含具体技术或量化信息")

    if policy.min_content_chars and content_chars < policy.min_content_chars:
        failures.append(f"正文 {content_chars} 字符，低于 {policy.min_content_chars}")
    if policy.min_summary_chars and summary_chars < policy.min_summary_chars:
        failures.append(f"摘要 {summary_chars} 字符，低于 {policy.min_summary_chars}")
    if policy.reject_promotional and any(
        re.search(pattern, title, re.IGNORECASE) for pattern in _PROMOTIONAL_TITLE_PATTERNS
    ):
        failures.append("标题属于活动、招聘或周报等低信号内容")

    documentation_signals = 0
    if source.kind == "github":
        repository = _repository_metadata(item)
        stars = _safe_int(repository.get("stars"))
        forks = _safe_int(repository.get("forks"))
        description = " ".join(str(repository.get("description") or "").split())
        license_name = str(repository.get("license") or "").strip()
        topics = repository.get("topics") or []
        documentation_signals = _documentation_signal_count(content)

        if stars >= 1_000:
            score += 22
        elif stars >= 100:
            score += 18
        elif stars >= 30:
            score += 15
        elif stars >= 10:
            score += 12
        elif stars >= 5:
            score += 7
        elif stars >= 1:
            score += 3
        if stars:
            signals.append(f"Stars：{stars}")
        if forks >= 10:
            score += 8
        elif forks >= 3:
            score += 5
        elif forks >= 1:
            score += 2
        if forks:
            signals.append(f"Forks：{forks}")
        if license_name:
            score += 6
            signals.append(f"许可证：{license_name}")
        if len(description) >= 80:
            score += 5
        elif len(description) >= 40:
            score += 3
        if description:
            signals.append(f"项目简介 {len(description)} 字符")
        if documentation_signals >= 4:
            score += 10
        elif documentation_signals == 3:
            score += 8
        elif documentation_signals == 2:
            score += 5
        elif documentation_signals == 1:
            score += 2
        if documentation_signals:
            signals.append(f"README 文档信号：{documentation_signals}")
        if isinstance(topics, list) and topics:
            score += 2
            signals.append("提供 GitHub topics")

        if policy.min_stars and stars < policy.min_stars:
            failures.append(f"Stars {stars}，低于 {policy.min_stars}")
        if policy.min_forks and forks < policy.min_forks:
            failures.append(f"Forks {forks}，低于 {policy.min_forks}")
        if policy.min_description_chars and len(description) < policy.min_description_chars:
            failures.append(
                f"项目简介 {len(description)} 字符，低于 {policy.min_description_chars}"
            )
        if policy.min_documentation_signals and documentation_signals < policy.min_documentation_signals:
            failures.append(
                f"README 文档信号 {documentation_signals}，低于 {policy.min_documentation_signals}"
            )
        if policy.require_license and not license_name:
            failures.append("没有可识别的开源许可证")

    score = max(0, min(score, 100))
    if score < threshold:
        failures.append(f"综合质量分 {score}，低于 {threshold}")
    return QualityAssessment(
        score=score,
        threshold=threshold,
        accepted=not failures,
        signals=tuple(signals),
        failures=tuple(failures),
        documentation_signals=documentation_signals,
    )
