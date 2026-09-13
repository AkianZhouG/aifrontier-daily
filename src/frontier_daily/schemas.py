from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


SourceKind = Literal["rss", "atom", "sitemap", "github", "fixture"]
SourceTier = Literal["official", "paper", "community", "media"]


class SourceQualityConfig(BaseModel):
    min_score: int | None = Field(default=None, ge=0, le=100)
    min_event_importance: int | None = Field(default=None, ge=0, le=100)
    min_content_chars: int = Field(default=0, ge=0, le=100_000)
    min_summary_chars: int = Field(default=0, ge=0, le=20_000)
    min_stars: int = Field(default=0, ge=0, le=10_000_000)
    min_forks: int = Field(default=0, ge=0, le=10_000_000)
    min_description_chars: int = Field(default=0, ge=0, le=4_000)
    min_documentation_signals: int = Field(default=0, ge=0, le=10)
    require_license: bool = False
    reject_promotional: bool = True


class SourceConfig(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    kind: SourceKind
    url: str
    tier: SourceTier = "official"
    enabled: bool = True
    max_items: int = Field(default=20, ge=1, le=200)
    fetch_pages: bool = True
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    quality: SourceQualityConfig = Field(default_factory=SourceQualityConfig)


class CandidateItem(BaseModel):
    source_id: str
    source_name: str
    source_tier: SourceTier
    title: str
    url: str
    published_at: str | None = None
    discovered_at: str
    summary: str = ""
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractedClaim(BaseModel):
    key: str
    value: str
    material: bool = True

    @field_validator("key", "value")
    @classmethod
    def non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("关键事实的字段不能为空")
        return value


class ExtractedEvent(BaseModel):
    event_key: str = Field(min_length=3, max_length=240)
    entity: str = Field(min_length=1, max_length=120)
    subject: str = Field(min_length=1, max_length=180)
    event_type: str = Field(min_length=1, max_length=80)
    title_zh: str = Field(min_length=1, max_length=240)
    summary_zh: str = Field(min_length=1, max_length=1200)
    why_it_matters_zh: str = Field(default="", max_length=800)
    importance: int = Field(default=50, ge=0, le=100)
    confidence: Literal["high", "medium", "low"] = "medium"
    source_item_ids: list[int] = Field(min_length=1)
    claims: list[ExtractedClaim] = Field(default_factory=list)

    @field_validator("event_key")
    @classmethod
    def normalize_event_key(cls, value: str) -> str:
        return "|".join(part.strip().lower() for part in value.split("|") if part.strip())


class ExtractionBatch(BaseModel):
    events: list[ExtractedEvent] = Field(default_factory=list)


class EditionEntry(BaseModel):
    event_id: int
    item_type: Literal["new", "update", "focus", "related"]
    title: str
    summary: str
    why_it_matters: str
    source_name: str
    source_url: str
    published_at: str | None = None
    importance: int
    confidence: str
    delta_claims: list[str] = Field(default_factory=list)


class EditionDraft(BaseModel):
    date: str
    title: str
    overview: str
    trend_judgment: list[str] = Field(default_factory=list)
    items: list[EditionEntry] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class ItemRewrite(BaseModel):
    event_id: int
    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(min_length=1, max_length=1200)
    why_it_matters: str = Field(default="", max_length=800)


class EditionSynthesis(BaseModel):
    overview: str = Field(min_length=1, max_length=1800)
    trend_judgment: list[str] = Field(default_factory=list, max_length=6)
    caveats: list[str] = Field(default_factory=list, max_length=10)
    item_rewrites: list[ItemRewrite] = Field(default_factory=list)


class RuntimeSettings(BaseModel):
    schedule: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str
    max_items: int = Field(ge=1, le=30)
    lookback_hours: int = Field(ge=6, le=336)
    scheduler_paused: bool = False
    agent_binary: str | None = Field(default=None, min_length=1, max_length=500)
    agent_provider: str | None = Field(default=None, max_length=120)
    agent_model: str | None = Field(default=None, max_length=200)
    agent_thinking: Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"] | None = None
    focus_profile: str | None = Field(default=None, max_length=4000)


class RunRequest(BaseModel):
    fixture: str | None = None
    no_llm: bool = False


class EventAction(BaseModel):
    action: Literal["ignore", "restore", "force-next"]


def utc_now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
