from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_FOCUS_PROFILE = (
    "人工智能编程代理、智能体工具、代理模型、本地推理、推理优化、草稿模型、检索工具、技能插件、开发者工作流、智能体安全和 GitHub 有实际价值的开源项目。"
    "优先关注工具实际能力、模型选择、上下文与记忆、评测、许可证和可复现部署，过滤泛泛的消费产品、广告和与开发者工作流无关的新闻。"
)


def _as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


def project_root() -> Path:
    override = os.environ.get("FRONTIER_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class AppConfig:
    root: Path
    data_dir: Path
    logs_dir: Path
    artifacts_dir: Path
    runs_dir: Path
    db_path: Path
    frontend_dist: Path
    sources_path: Path
    timezone: str = "Asia/Shanghai"
    schedule_hour: int = 8
    schedule_minute: int = 30
    lookback_hours: int = 72
    catchup_hours: int = 12
    max_candidates: int = 36
    max_items: int = 8
    max_fetch_chars: int = 18_000
    host: str = "127.0.0.1"
    port: int = 8787
    llm_enabled: bool = False
    llm_required_for_ready: bool = False
    pi_binary: str = "pi"
    pi_provider: str = ""
    pi_model: str = ""
    pi_thinking: str = "medium"
    pi_timeout_seconds: int = 900
    focus_profile: str = DEFAULT_FOCUS_PROFILE

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def schedule_text(self) -> str:
        return f"{self.schedule_hour:02d}:{self.schedule_minute:02d}"

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.logs_dir, self.artifacts_dir, self.runs_dir):
            path.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"配置文件必须是 JSON 对象：{path}")
    return data


def load_config() -> AppConfig:
    root = project_root()
    example = root / "config" / "app.example.json"
    local = root / "config" / "app.json"
    raw = _read_json(local if local.exists() else example)
    llm = raw.get("llm") if isinstance(raw.get("llm"), dict) else {}
    agent = raw.get("agent") if isinstance(raw.get("agent"), dict) else {}

    schedule = str(os.environ.get("FRONTIER_SCHEDULE", raw.get("schedule", "08:30")))
    try:
        hour_text, minute_text = schedule.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError as exc:
        raise ValueError(f"运行时间无效：{schedule!r}，格式应为 HH:MM") from exc

    data_dir = Path(os.environ.get("FRONTIER_DATA_DIR", root / "data")).expanduser().resolve()
    logs_dir = Path(os.environ.get("FRONTIER_LOGS_DIR", root / "logs")).expanduser().resolve()
    pi_binary = os.environ.get(
        "FRONTIER_AGENT_BINARY",
        os.environ.get("FRONTIER_PI_BINARY", str(agent.get("binary", llm.get("pi_binary", "pi")))),
    )
    resolved_pi = shutil.which(pi_binary) or pi_binary
    pi_provider = os.environ.get(
        "FRONTIER_AGENT_PROVIDER",
        os.environ.get("FRONTIER_PI_PROVIDER", str(agent.get("provider", llm.get("provider", "")))),
    )
    pi_model = os.environ.get(
        "FRONTIER_AGENT_MODEL",
        os.environ.get("FRONTIER_PI_MODEL", str(agent.get("model", llm.get("model", "")))),
    )
    pi_thinking = os.environ.get(
        "FRONTIER_AGENT_THINKING",
        os.environ.get("FRONTIER_PI_THINKING", str(agent.get("thinking", llm.get("thinking", "medium")))),
    )
    focus_profile = str(
        os.environ.get("FRONTIER_FOCUS_PROFILE", raw.get("focus_profile", DEFAULT_FOCUS_PROFILE))
    ).strip()

    config = AppConfig(
        root=root,
        data_dir=data_dir,
        logs_dir=logs_dir,
        artifacts_dir=data_dir / "editions",
        runs_dir=data_dir / "runs",
        db_path=Path(os.environ.get("FRONTIER_DB", data_dir / "frontier.sqlite3")).expanduser().resolve(),
        frontend_dist=root / "frontend" / "dist",
        sources_path=root / "config" / "sources.json",
        timezone=str(os.environ.get("FRONTIER_TIMEZONE", raw.get("timezone", "Asia/Shanghai"))),
        schedule_hour=hour,
        schedule_minute=minute,
        lookback_hours=int(raw.get("lookback_hours", 72)),
        catchup_hours=int(raw.get("catchup_hours", 12)),
        max_candidates=int(raw.get("max_candidates", 36)),
        max_items=int(raw.get("max_items", 8)),
        max_fetch_chars=int(raw.get("max_fetch_chars", 18_000)),
        host=str(os.environ.get("FRONTIER_HOST", raw.get("host", "127.0.0.1"))),
        port=int(os.environ.get("FRONTIER_PORT", raw.get("port", 8787))),
        llm_enabled=_as_bool(
            os.environ.get("FRONTIER_LLM_ENABLED", agent.get("enabled", llm.get("enabled", False))),
            default=False,
        ),
        llm_required_for_ready=_as_bool(
            agent.get("required_for_ready", llm.get("required_for_ready", False))
        ),
        pi_binary=resolved_pi,
        pi_provider=pi_provider,
        pi_model=pi_model,
        pi_thinking=pi_thinking,
        pi_timeout_seconds=int(
            os.environ.get(
                "FRONTIER_AGENT_TIMEOUT",
                os.environ.get("FRONTIER_PI_TIMEOUT", agent.get("timeout_seconds", llm.get("timeout_seconds", 900))),
            )
        ),
        focus_profile=focus_profile or DEFAULT_FOCUS_PROFILE,
    )
    config.tz  # validate zone eagerly
    config.ensure_directories()
    return config


def install_local_config(config: AppConfig) -> Path:
    target = config.root / "config" / "app.json"
    if not target.exists():
        shutil.copy2(config.root / "config" / "app.example.json", target)
    return target
