from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .config import AppConfig
from .localization import localize_claim_text
from .quality import QUALITY_POLICY_VERSION
from .schemas import ExtractedEvent, SourceConfig, utc_now_iso


SCHEMA_VERSION = 1
ACTIVE_RUN_STATES = ("queued", "running")


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @contextmanager
    def transaction(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.transaction(immediate=True) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    version INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    url TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    config_json TEXT NOT NULL,
                    last_success_at TEXT,
                    last_failure_at TEXT,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS source_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL REFERENCES sources(id),
                    url TEXT NOT NULL,
                    canonical_url TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    published_at TEXT,
                    discovered_at TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'candidate',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_source_items_published ON source_items(published_at DESC);
                CREATE INDEX IF NOT EXISTS idx_source_items_hash ON source_items(content_hash);

                CREATE TABLE IF NOT EXISTS run_items (
                    run_id TEXT NOT NULL REFERENCES job_runs(run_id) ON DELETE CASCADE,
                    item_id INTEGER NOT NULL REFERENCES source_items(id) ON DELETE CASCADE,
                    disposition TEXT NOT NULL DEFAULT 'candidate',
                    reason TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (run_id, item_id)
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT NOT NULL UNIQUE,
                    entity TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    title_zh TEXT NOT NULL,
                    summary_zh TEXT NOT NULL,
                    why_it_matters_zh TEXT NOT NULL DEFAULT '',
                    importance INTEGER NOT NULL DEFAULT 50,
                    confidence TEXT NOT NULL DEFAULT 'medium',
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    force_next INTEGER NOT NULL DEFAULT 0,
                    canonical_source_item_id INTEGER REFERENCES source_items(id)
                );
                CREATE INDEX IF NOT EXISTS idx_events_last_seen ON events(last_seen_at DESC);

                CREATE TABLE IF NOT EXISTS event_aliases (
                    alias_key TEXT PRIMARY KEY,
                    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS event_sources (
                    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                    item_id INTEGER NOT NULL REFERENCES source_items(id) ON DELETE CASCADE,
                    PRIMARY KEY (event_id, item_id)
                );

                CREATE TABLE IF NOT EXISTS claims (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                    claim_key TEXT NOT NULL,
                    claim_value TEXT NOT NULL,
                    claim_hash TEXT NOT NULL,
                    material INTEGER NOT NULL DEFAULT 1,
                    first_seen_at TEXT NOT NULL,
                    UNIQUE (event_id, claim_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_claims_event ON claims(event_id);

                CREATE TABLE IF NOT EXISTS run_events (
                    run_id TEXT NOT NULL REFERENCES job_runs(run_id) ON DELETE CASCADE,
                    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                    decision TEXT NOT NULL,
                    delta_json TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY (run_id, event_id)
                );

                CREATE TABLE IF NOT EXISTS editions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    edition_date TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    overview TEXT NOT NULL DEFAULT '',
                    json_path TEXT,
                    html_path TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS edition_items (
                    edition_id INTEGER NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
                    event_id INTEGER NOT NULL REFERENCES events(id),
                    item_type TEXT NOT NULL,
                    delta_hash TEXT NOT NULL DEFAULT '',
                    position INTEGER NOT NULL,
                    PRIMARY KEY (edition_id, event_id)
                );
                CREATE INDEX IF NOT EXISTS idx_edition_items_event ON edition_items(event_id);

                CREATE TABLE IF NOT EXISTS job_runs (
                    run_id TEXT PRIMARY KEY,
                    trigger_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress_pct REAL NOT NULL DEFAULT 0,
                    current_step TEXT NOT NULL DEFAULT '',
                    edition_date TEXT NOT NULL,
                    pid INTEGER,
                    started_at TEXT,
                    finished_at TEXT,
                    error TEXT,
                    log_path TEXT NOT NULL,
                    fixture_path TEXT,
                    no_llm INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_job_runs_created ON job_runs(created_at DESC);

                CREATE TABLE IF NOT EXISTS job_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES job_runs(run_id) ON DELETE CASCADE,
                    step_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    detail TEXT NOT NULL DEFAULT '',
                    UNIQUE (run_id, step_name)
                );

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            row = conn.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
            if row is None:
                conn.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
            elif int(row["version"]) != SCHEMA_VERSION:
                raise RuntimeError(
                    f"database schema {row['version']} is not supported; expected {SCHEMA_VERSION}"
                )

    def seed_sources(self, sources: list[SourceConfig]) -> None:
        now = utc_now_iso()
        with self.transaction(immediate=True) as conn:
            for source in sources:
                payload = source.model_dump_json()
                conn.execute(
                    """
                    INSERT INTO sources(id, name, kind, url, tier, enabled, config_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                      name=excluded.name,
                      kind=excluded.kind,
                      url=excluded.url,
                      tier=excluded.tier,
                      config_json=excluded.config_json,
                      updated_at=excluded.updated_at
                    """,
                    (
                        source.id,
                        source.name,
                        source.kind,
                        source.url,
                        source.tier,
                        int(source.enabled),
                        payload,
                        now,
                    ),
                )

    def list_sources(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM sources"
        if enabled_only:
            query += " WHERE enabled=1"
        query += " ORDER BY tier DESC, name"
        with self.connect() as conn:
            rows = conn.execute(query).fetchall()
            latest_run = conn.execute(
                "SELECT run_id FROM job_runs WHERE status='completed' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            quality_rows = (
                conn.execute(
                    """SELECT i.source_id, i.metadata_json
                       FROM run_items r JOIN source_items i ON i.id=r.item_id
                       WHERE r.run_id=?""",
                    (latest_run["run_id"],),
                ).fetchall()
                if latest_run
                else []
            )
        quality_by_source: dict[str, dict[str, int]] = {}
        for row in quality_rows:
            stats = quality_by_source.setdefault(
                str(row["source_id"]),
                {"examined": 0, "accepted": 0, "rejected": 0, "unassessed": 0},
            )
            stats["examined"] += 1
            metadata = json.loads(row["metadata_json"] or "{}")
            quality = metadata.get("quality") if isinstance(metadata, dict) else None
            if not isinstance(quality, dict) or quality.get("version") != QUALITY_POLICY_VERSION:
                stats["unassessed"] += 1
            elif quality.get("accepted") is True:
                stats["accepted"] += 1
            else:
                stats["rejected"] += 1
        result = []
        for row in rows:
            item = dict(row)
            item["enabled"] = bool(item["enabled"])
            item["config"] = json.loads(item.pop("config_json"))
            item["quality_last_run"] = quality_by_source.get(
                item["id"],
                {"examined": 0, "accepted": 0, "rejected": 0, "unassessed": 0},
            )
            result.append(item)
        return result

    def set_source_enabled(self, source_id: str, enabled: bool) -> bool:
        with self.transaction(immediate=True) as conn:
            cur = conn.execute(
                "UPDATE sources SET enabled=?, updated_at=? WHERE id=?",
                (int(enabled), utc_now_iso(), source_id),
            )
            return cur.rowcount == 1

    def source_success(self, source_id: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                """UPDATE sources SET last_success_at=?, consecutive_failures=0,
                   last_error=NULL, updated_at=? WHERE id=?""",
                (utc_now_iso(), utc_now_iso(), source_id),
            )

    def source_failure(self, source_id: str, error: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                """UPDATE sources SET last_failure_at=?, consecutive_failures=consecutive_failures+1,
                   last_error=?, updated_at=? WHERE id=?""",
                (utc_now_iso(), error[:1000], utc_now_iso(), source_id),
            )

    def active_run(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM job_runs WHERE status IN ('queued','running') ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def create_run(
        self,
        *,
        trigger_type: str,
        edition_date: str,
        log_path: Path,
        fixture_path: str | None = None,
        no_llm: bool = False,
    ) -> str:
        run_id = uuid.uuid4().hex[:12]
        with self.transaction(immediate=True) as conn:
            active = conn.execute(
                "SELECT run_id FROM job_runs WHERE status IN ('queued','running') ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if active:
                return str(active["run_id"])
            conn.execute(
                """
                INSERT INTO job_runs(
                  run_id, trigger_type, status, edition_date, log_path,
                  fixture_path, no_llm, created_at
                ) VALUES (?, ?, 'queued', ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    trigger_type,
                    edition_date,
                    str(log_path),
                    fixture_path,
                    int(no_llm),
                    utc_now_iso(),
                ),
            )
        return run_id

    def update_run(self, run_id: str, **fields: Any) -> None:
        allowed = {
            "status",
            "progress_pct",
            "current_step",
            "pid",
            "started_at",
            "finished_at",
            "error",
        }
        values = {key: value for key, value in fields.items() if key in allowed}
        if not values:
            return
        assignments = ", ".join(f"{key}=?" for key in values)
        with self.transaction() as conn:
            conn.execute(
                f"UPDATE job_runs SET {assignments} WHERE run_id=?",
                (*values.values(), run_id),
            )

    def step(self, run_id: str, step_name: str, status: str, detail: str = "") -> None:
        now = utc_now_iso()
        started = now if status == "running" else None
        finished = now if status in {"completed", "failed", "skipped"} else None
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO job_steps(run_id, step_name, status, started_at, finished_at, detail)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, step_name) DO UPDATE SET
                  status=excluded.status,
                  started_at=COALESCE(job_steps.started_at, excluded.started_at),
                  finished_at=excluded.finished_at,
                  detail=excluded.detail
                """,
                (run_id, step_name, status, started, finished, detail[:4000]),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM job_runs WHERE run_id=?", (run_id,)).fetchone()
            if not row:
                return None
            steps = conn.execute(
                "SELECT step_name, status, started_at, finished_at, detail FROM job_steps WHERE run_id=? ORDER BY id",
                (run_id,),
            ).fetchall()
        result = dict(row)
        result["no_llm"] = bool(result["no_llm"])
        result["steps"] = [dict(step) for step in steps]
        return result

    def list_runs(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM job_runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def recover_stale_runs(self) -> int:
        now = utc_now_iso()
        with self.transaction(immediate=True) as conn:
            cur = conn.execute(
                """UPDATE job_runs SET status='failed', finished_at=?,
                   error='服务重启时任务仍在执行，已标记为失败'
                   WHERE status IN ('queued','running')""",
                (now,),
            )
            return cur.rowcount

    def add_source_item(
        self,
        *,
        run_id: str,
        source_id: str,
        url: str,
        canonical_url: str,
        title: str,
        published_at: str | None,
        discovered_at: str,
        summary: str,
        content: str,
        content_hash: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[int, bool]:
        now = utc_now_iso()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
        with self.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT id, content_hash FROM source_items WHERE canonical_url=?",
                (canonical_url,),
            ).fetchone()
            is_new = row is None
            if row is None:
                cur = conn.execute(
                    """
                    INSERT INTO source_items(
                      source_id, url, canonical_url, title, published_at, discovered_at,
                      summary, content, content_hash, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        url,
                        canonical_url,
                        title[:500],
                        published_at,
                        discovered_at,
                        summary,
                        content,
                        content_hash,
                        metadata_json,
                        now,
                        now,
                    ),
                )
                item_id = int(cur.lastrowid)
            else:
                item_id = int(row["id"])
                content_changed = bool(content_hash and content_hash != row["content_hash"])
                if content_changed:
                    conn.execute(
                        """UPDATE source_items SET source_id=?, url=?, title=?, published_at=COALESCE(?,published_at),
                           summary=?, content=?, content_hash=?, metadata_json=?, updated_at=? WHERE id=?""",
                        (
                            source_id,
                            url,
                            title[:500],
                            published_at,
                            summary,
                            content,
                            content_hash,
                            metadata_json,
                            now,
                            item_id,
                        ),
                    )
                    is_new = True
                else:
                    conn.execute(
                        """UPDATE source_items SET source_id=?, url=?, title=?,
                           published_at=COALESCE(?,published_at), summary=?, content=?,
                           metadata_json=?, updated_at=? WHERE id=?""",
                        (
                            source_id,
                            url,
                            title[:500],
                            published_at,
                            summary,
                            content,
                            metadata_json,
                            now,
                            item_id,
                        ),
                    )
            conn.execute(
                """INSERT INTO run_items(run_id,item_id,disposition)
                   VALUES (?,?,'candidate')
                   ON CONFLICT(run_id,item_id) DO NOTHING""",
                (run_id, item_id),
            )
            return item_id, is_new

    def set_run_item_disposition(self, run_id: str, item_id: int, disposition: str, reason: str = "") -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE run_items SET disposition=?, reason=? WHERE run_id=? AND item_id=?",
                (disposition, reason[:1000], run_id, item_id),
            )

    def content_duplicate(self, item_id: int, content_hash: str) -> dict[str, Any] | None:
        if not content_hash:
            return None
        with self.connect() as conn:
            row = conn.execute(
                """SELECT id, canonical_url, title FROM source_items
                   WHERE content_hash=? AND id<>? ORDER BY id LIMIT 1""",
                (content_hash, item_id),
            ).fetchone()
        return dict(row) if row else None

    def run_source_items(self, run_id: str, candidates_only: bool = True) -> list[dict[str, Any]]:
        query = """
            SELECT i.*, s.name AS source_name, s.kind AS source_kind,
                   s.tier AS source_tier, r.disposition, r.reason
            FROM run_items r
            JOIN source_items i ON i.id=r.item_id
            JOIN sources s ON s.id=i.source_id
            WHERE r.run_id=?
        """
        params: list[Any] = [run_id]
        if candidates_only:
            query += " AND r.disposition='candidate'"
        query += " ORDER BY COALESCE(i.published_at,i.discovered_at) DESC"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            result.append(item)
        return result

    def event_source_profiles(self, event_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT s.id AS source_id, s.name AS source_name, s.kind AS source_kind,
                          s.tier AS source_tier, i.id AS source_item_id, i.metadata_json
                   FROM event_sources es
                   JOIN source_items i ON i.id=es.item_id
                   JOIN sources s ON s.id=i.source_id
                   WHERE es.event_id=? ORDER BY i.id""",
                (event_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            result.append(item)
        return result

    @staticmethod
    def _claim_hash(key: str, value: str) -> str:
        normalized = " ".join(f"{key.strip().lower()} {value.strip().lower()}".split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def upsert_event(self, run_id: str, event: ExtractedEvent) -> tuple[int, str, list[str]]:
        now = utc_now_iso()
        item_ids = list(dict.fromkeys(event.source_item_ids))
        if not item_ids:
            raise ValueError("event requires at least one source item")
        with self.transaction(immediate=True) as conn:
            placeholders = ",".join("?" for _ in item_ids)
            existing = conn.execute(
                f"""SELECT e.* FROM event_sources es
                    JOIN events e ON e.id=es.event_id
                    WHERE es.item_id IN ({placeholders})
                    ORDER BY e.id LIMIT 1""",
                item_ids,
            ).fetchone()
            if existing is None:
                existing = conn.execute(
                    """SELECT e.* FROM event_aliases a
                       JOIN events e ON e.id=a.event_id WHERE a.alias_key=?""",
                    (event.event_key,),
                ).fetchone()
            if existing is None:
                existing = conn.execute(
                    "SELECT * FROM events WHERE event_key=?", (event.event_key,)
                ).fetchone()
            if existing is None:
                cur = conn.execute(
                    """
                    INSERT INTO events(
                      event_key,entity,subject,event_type,title_zh,summary_zh,why_it_matters_zh,
                      importance,confidence,first_seen_at,last_seen_at,canonical_source_item_id
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event.event_key,
                        event.entity,
                        event.subject,
                        event.event_type,
                        event.title_zh,
                        event.summary_zh,
                        event.why_it_matters_zh,
                        event.importance,
                        event.confidence,
                        now,
                        now,
                        item_ids[0],
                    ),
                )
                event_id = int(cur.lastrowid)
                decision = "new"
            else:
                event_id = int(existing["id"])
                conn.execute(
                    """UPDATE events SET last_seen_at=?, title_zh=?, summary_zh=?,
                       why_it_matters_zh=?, importance=MAX(importance,?), confidence=? WHERE id=?""",
                    (
                        now,
                        event.title_zh,
                        event.summary_zh,
                        event.why_it_matters_zh,
                        event.importance,
                        event.confidence,
                        event_id,
                    ),
                )
                decision = "duplicate"

            conn.execute(
                "INSERT OR IGNORE INTO event_aliases(alias_key,event_id) VALUES (?,?)",
                (event.event_key, event_id),
            )
            for item_id in item_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO event_sources(event_id,item_id) VALUES (?,?)",
                    (event_id, item_id),
                )

            new_material: list[str] = []
            for claim in event.claims:
                claim_hash = self._claim_hash(claim.key, claim.value)
                cur = conn.execute(
                    """INSERT OR IGNORE INTO claims(
                         event_id,claim_key,claim_value,claim_hash,material,first_seen_at
                       ) VALUES (?,?,?,?,?,?)""",
                    (
                        event_id,
                        claim.key,
                        claim.value,
                        claim_hash,
                        int(claim.material),
                        now,
                    ),
                )
                if cur.rowcount and claim.material:
                    new_material.append(localize_claim_text(f"{claim.key}: {claim.value}"))

            if existing is not None and new_material:
                decision = "update"
            if existing is not None and bool(existing["force_next"]):
                decision = "update"
                conn.execute("UPDATE events SET force_next=0 WHERE id=?", (event_id,))
                if not new_material:
                    new_material.append("manual: force next edition")

            conn.execute(
                """
                INSERT INTO run_events(run_id,event_id,decision,delta_json)
                VALUES (?,?,?,?)
                ON CONFLICT(run_id,event_id) DO UPDATE SET
                  decision=excluded.decision,
                  delta_json=excluded.delta_json
                """,
                (run_id, event_id, decision, json.dumps(new_material, ensure_ascii=False)),
            )
            for item_id in item_ids:
                conn.execute(
                    "UPDATE run_items SET disposition=?, reason=? WHERE run_id=? AND item_id=?",
                    (
                        "accepted" if decision in {"new", "update"} else "duplicate",
                        f"event:{event.event_key}:{decision}",
                        run_id,
                        item_id,
                    ),
                )
        return event_id, decision, new_material

    def run_events(self, run_id: str, include_duplicates: bool = False) -> list[dict[str, Any]]:
        query = """
            SELECT e.*, r.decision, r.delta_json,
                   i.canonical_url AS source_url, i.title AS source_title,
                   i.published_at, s.name AS source_name
            FROM run_events r
            JOIN events e ON e.id=r.event_id
            LEFT JOIN source_items i ON i.id=e.canonical_source_item_id
            LEFT JOIN sources s ON s.id=i.source_id
            WHERE r.run_id=? AND e.status='active'
        """
        if not include_duplicates:
            query += " AND r.decision IN ('new','update')"
        query += " ORDER BY e.importance DESC, e.last_seen_at DESC"
        with self.connect() as conn:
            rows = conn.execute(query, (run_id,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["delta_claims"] = json.loads(item.pop("delta_json") or "[]")
            result.append(item)
        return result

    def upsert_edition_draft(self, edition_date: str) -> int:
        now = utc_now_iso()
        with self.transaction(immediate=True) as conn:
            conn.execute(
                """
                INSERT INTO editions(edition_date,status,created_at,updated_at)
                VALUES (?,'draft',?,?)
                ON CONFLICT(edition_date) DO UPDATE SET
                  status='draft', error=NULL, updated_at=excluded.updated_at
                """,
                (edition_date, now, now),
            )
            row = conn.execute(
                "SELECT id FROM editions WHERE edition_date=?", (edition_date,)
            ).fetchone()
            return int(row["id"])

    def commit_edition(
        self,
        *,
        edition_date: str,
        status: str,
        title: str,
        overview: str,
        json_path: Path,
        html_path: Path,
        events: list[dict[str, Any]],
    ) -> int:
        if not json_path.is_file() or not html_path.is_file():
            raise ValueError("提交日报前必须先生成日报文件")
        now = utc_now_iso()
        with self.transaction(immediate=True) as conn:
            row = conn.execute(
                "SELECT id FROM editions WHERE edition_date=?", (edition_date,)
            ).fetchone()
            if row is None:
                cur = conn.execute(
                    """INSERT INTO editions(
                         edition_date,status,title,overview,json_path,html_path,created_at,updated_at
                       ) VALUES (?,?,?,?,?,?,?,?)""",
                    (edition_date, status, title, overview, str(json_path), str(html_path), now, now),
                )
                edition_id = int(cur.lastrowid)
            else:
                edition_id = int(row["id"])
                conn.execute(
                    """UPDATE editions SET status=?,title=?,overview=?,json_path=?,html_path=?,
                       error=NULL,updated_at=? WHERE id=?""",
                    (status, title, overview, str(json_path), str(html_path), now, edition_id),
                )
                conn.execute("DELETE FROM edition_items WHERE edition_id=?", (edition_id,))
            for position, event in enumerate(events, start=1):
                delta = event.get("delta_claims") or []
                delta_hash = hashlib.sha256(
                    json.dumps(delta, ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest()
                conn.execute(
                    """INSERT INTO edition_items(
                         edition_id,event_id,item_type,delta_hash,position
                       ) VALUES (?,?,?,?,?)""",
                    (edition_id, event["id"], event["decision"], delta_hash, position),
                )
            return edition_id

    def fail_edition(self, edition_date: str, error: str) -> None:
        now = utc_now_iso()
        with self.transaction(immediate=True) as conn:
            conn.execute(
                """INSERT INTO editions(edition_date,status,error,created_at,updated_at)
                   VALUES (?,'failed',?,?,?)
                   ON CONFLICT(edition_date) DO UPDATE SET
                     status='failed',error=excluded.error,updated_at=excluded.updated_at""",
                (edition_date, error[:4000], now, now),
            )

    def edition_for_date(self, edition_date: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM editions WHERE edition_date=?", (edition_date,)
            ).fetchone()
            if not row:
                return None
            items = conn.execute(
                """SELECT e.*, ei.item_type, ei.position,
                          i.canonical_url AS source_url, s.name AS source_name, i.published_at
                   FROM edition_items ei JOIN events e ON e.id=ei.event_id
                   LEFT JOIN source_items i ON i.id=e.canonical_source_item_id
                   LEFT JOIN sources s ON s.id=i.source_id
                   WHERE ei.edition_id=? ORDER BY ei.position""",
                (row["id"],),
            ).fetchall()
        result = dict(row)
        result["items"] = [dict(item) for item in items]
        return result

    def list_editions(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT e.*, COUNT(i.event_id) AS item_count
                   FROM editions e LEFT JOIN edition_items i ON i.edition_id=e.id
                   GROUP BY e.id ORDER BY e.edition_date DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT e.*, i.canonical_url AS source_url, i.title AS source_title,
                   i.published_at, s.name AS source_name,
                   (SELECT COUNT(*) FROM event_sources es WHERE es.event_id=e.id) AS source_count,
                   (SELECT COUNT(*) FROM claims c WHERE c.event_id=e.id) AS claim_count,
                   (SELECT MAX(ed.edition_date) FROM edition_items ei JOIN editions ed ON ed.id=ei.edition_id WHERE ei.event_id=e.id) AS last_edition
            FROM events e
            LEFT JOIN source_items i ON i.id=e.canonical_source_item_id
            LEFT JOIN sources s ON s.id=i.source_id
        """
        params: list[Any] = []
        if status:
            query += " WHERE e.status=?"
            params.append(status)
        query += " ORDER BY e.last_seen_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
            result = []
            for row in rows:
                event = dict(row)
                claims = conn.execute(
                    "SELECT claim_key,claim_value,material,first_seen_at FROM claims WHERE event_id=? ORDER BY id",
                    (event["id"],),
                ).fetchall()
                event["claims"] = [dict(claim) for claim in claims]
                result.append(event)
        return result

    def event_action(self, event_id: int, action: str) -> bool:
        with self.transaction(immediate=True) as conn:
            if action == "ignore":
                cur = conn.execute("UPDATE events SET status='ignored' WHERE id=?", (event_id,))
            elif action == "restore":
                cur = conn.execute("UPDATE events SET status='active' WHERE id=?", (event_id,))
            elif action == "force-next":
                cur = conn.execute("UPDATE events SET status='active', force_next=1 WHERE id=?", (event_id,))
            else:
                return False
            return cur.rowcount == 1

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.connect() as conn:
            row = conn.execute("SELECT value_json FROM app_settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value_json"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        with self.transaction(immediate=True) as conn:
            conn.execute(
                """INSERT INTO app_settings(key,value_json,updated_at) VALUES (?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at""",
                (key, json.dumps(value, ensure_ascii=False), utc_now_iso()),
            )

    def dashboard(self) -> dict[str, Any]:
        with self.connect() as conn:
            counts = {
                "sources": conn.execute("SELECT COUNT(*) FROM sources WHERE enabled=1").fetchone()[0],
                "events": conn.execute("SELECT COUNT(*) FROM events WHERE status='active'").fetchone()[0],
                "items": conn.execute("SELECT COUNT(*) FROM source_items").fetchone()[0],
                "editions": conn.execute("SELECT COUNT(*) FROM editions WHERE status IN ('ready','partial')").fetchone()[0],
            }
            last_run = conn.execute("SELECT * FROM job_runs ORDER BY created_at DESC LIMIT 1").fetchone()
            last_edition = conn.execute("SELECT * FROM editions ORDER BY edition_date DESC LIMIT 1").fetchone()
            source_failures = conn.execute(
                "SELECT COUNT(*) FROM sources WHERE enabled=1 AND consecutive_failures>0"
            ).fetchone()[0]
        return {
            "counts": counts,
            "last_run": dict(last_run) if last_run else None,
            "last_edition": dict(last_edition) if last_edition else None,
            "unhealthy_sources": source_failures,
        }


def load_source_configs(config: AppConfig) -> list[SourceConfig]:
    with config.sources_path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, list):
        raise ValueError("config/sources.json 必须包含 JSON 数组")
    return [SourceConfig.model_validate(item) for item in raw]


def open_database(config: AppConfig) -> Database:
    db = Database(config.db_path)
    db.initialize()
    sources = load_source_configs(config)
    db.seed_sources(sources)
    focus_missing = db.get_setting("focus_profile") is None
    defaults = {
        "schedule": config.schedule_text,
        "timezone": config.timezone,
        "max_items": config.max_items,
        "lookback_hours": config.lookback_hours,
        "scheduler_paused": False,
        "agent_binary": config.pi_binary,
        "agent_provider": config.pi_provider,
        "agent_model": config.pi_model,
        "agent_thinking": config.pi_thinking,
        "focus_profile": config.focus_profile,
        "report_rebuild_requested": False,
    }
    for key, value in defaults.items():
        if db.get_setting(key) is None:
            db.set_setting(key, value)
    has_editions = bool(db.dashboard()["counts"]["editions"])
    if focus_missing and has_editions:
        db.set_setting("report_rebuild_requested", True)

    quality_payload = {
        "version": QUALITY_POLICY_VERSION,
        "sources": [
            {
                "id": source.id,
                "kind": source.kind,
                "tier": source.tier,
                "quality": source.quality.model_dump(mode="json"),
            }
            for source in sorted(sources, key=lambda item: item.id)
        ],
    }
    quality_fingerprint = hashlib.sha256(
        json.dumps(quality_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    previous_quality_fingerprint = db.get_setting("quality_policy_fingerprint")
    if previous_quality_fingerprint != quality_fingerprint:
        db.set_setting("quality_policy_fingerprint", quality_fingerprint)
        if has_editions:
            db.set_setting("report_rebuild_requested", True)
    return db
