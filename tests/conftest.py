from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from frontier_daily.config import AppConfig, load_config
from frontier_daily.db import open_database


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    base = load_config()
    data = tmp_path / "data"
    logs = tmp_path / "logs"
    config = replace(
        base,
        data_dir=data,
        logs_dir=logs,
        artifacts_dir=data / "editions",
        runs_dir=data / "runs",
        db_path=data / "frontier.sqlite3",
        schedule_hour=23,
        schedule_minute=59,
        llm_enabled=False,
    )
    config.ensure_directories()
    return config


@pytest.fixture
def db(app_config: AppConfig):
    return open_database(app_config)
