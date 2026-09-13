from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlparse

from .content import normalize_text
from .schemas import ExtractedClaim, ExtractedEvent


def content_fingerprint(title: str, content: str, summary: str = "") -> str:
    normalized = normalize_text(content or summary or title)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def claim_fingerprint(key: str, value: str) -> str:
    normalized = normalize_text(f"{key} {value}")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _key_part(value: str, limit: int = 80) -> str:
    value = unicodedata.normalize("NFKC", value).lower()
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"[^\w\u3400-\u9fff]+", "-", value, flags=re.UNICODE)
    return value.strip("-")[:limit] or "unknown"


def infer_event_type(title: str) -> str:
    lower = title.lower()
    patterns = [
        ("release", ("release", "launch", "introducing", "发布", "上线", "开源")),
        ("research", ("paper", "research", "study", "benchmark", "论文", "研究", "评测")),
        ("safety", ("safety", "risk", "security", "alignment", "安全", "风险")),
        ("policy", ("policy", "regulation", "act", "治理", "法规", "政策")),
        ("funding", ("funding", "raises", "acquisition", "融资", "收购")),
        ("update", ("update", "improving", "upgrade", "更新", "升级")),
    ]
    for event_type, words in patterns:
        if any(word in lower for word in words):
            return event_type
    return "news"


def fallback_event(item: dict, *, item_id: int) -> ExtractedEvent:
    title = str(item.get("title") or "Untitled")
    source_name = str(item.get("source_name") or item.get("source_id") or "未知来源")
    event_type = infer_event_type(title)
    subject = re.sub(
        r"\b(introducing|announcing|launching|release|released|new|the|a|an)\b",
        " ",
        title,
        flags=re.IGNORECASE,
    )
    subject = " ".join(subject.split())[:180] or title[:180]
    event_key = f"{_key_part(source_name)}|{_key_part(subject)}|{event_type}"
    summary = str(item.get("summary") or "").strip()
    content = str(item.get("content") or "").strip()
    if not summary:
        summary = " ".join(content.split())[:500]
    if not summary:
        summary = title
    claim_value = " ".join(summary.split())[:500]
    importance = 70 if item.get("source_tier") in {"official", "paper"} else 50
    if event_type in {"release", "safety", "research"}:
        importance += 8
    return ExtractedEvent(
        event_key=event_key,
        entity=source_name,
        subject=subject,
        event_type=event_type,
        title_zh=title,
        summary_zh=summary[:1000],
        why_it_matters_zh="等待模型综合；当前为确定性降级摘要。",
        importance=min(importance, 100),
        confidence="medium" if item.get("source_tier") in {"official", "paper"} else "low",
        source_item_ids=[item_id],
        claims=[ExtractedClaim(key="source-summary", value=claim_value, material=True)],
    )


def domain_label(url: str) -> str:
    host = (urlparse(url).hostname or "unknown").lower()
    return host.removeprefix("www.")
