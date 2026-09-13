from __future__ import annotations

from datetime import datetime
from typing import Protocol

from frontier_daily.schemas import CandidateItem, SourceConfig


class Collector(Protocol):
    def collect(self, source: SourceConfig, since: datetime) -> list[CandidateItem]: ...
