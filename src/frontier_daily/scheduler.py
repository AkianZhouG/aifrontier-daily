from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import AppConfig
from .db import Database
from .security import minimal_subprocess_env
from .schemas import utc_now_iso


class JobManager:
    def __init__(self, config: AppConfig, db: Database):
        self.config = config
        self.db = db
        self._lock = threading.Lock()
        self._processes: dict[str, subprocess.Popen] = {}

    def start(
        self,
        *,
        trigger_type: str,
        fixture: str | None = None,
        no_llm: bool = False,
    ) -> str:
        edition_date = datetime.now(self.config.tz).date().isoformat()
        log_path = self.config.logs_dir / f"run-{datetime.now(self.config.tz):%Y%m%d-%H%M%S}.jsonl"
        with self._lock:
            run_id = self.db.create_run(
                trigger_type=trigger_type,
                edition_date=edition_date,
                log_path=log_path,
                fixture_path=fixture,
                no_llm=no_llm,
            )
            run = self.db.get_run(run_id)
            if run and run["status"] == "running":
                return run_id
            if run_id in self._processes and self._processes[run_id].poll() is None:
                return run_id

            run_dir = self.config.runs_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            console = (run_dir / "worker-console.log").open("ab", buffering=0)
            cmd = [sys.executable, "-m", "frontier_daily.worker", "--run-id", run_id]
            env = minimal_subprocess_env(
                extra={
                    "FRONTIER_ROOT": str(self.config.root),
                    "FRONTIER_DATA_DIR": str(self.config.data_dir),
                    "FRONTIER_LOGS_DIR": str(self.config.logs_dir),
                }
            )
            process = subprocess.Popen(
                cmd,
                cwd=self.config.root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=console,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            console.close()
            self._processes[run_id] = process
            self.db.update_run(run_id, pid=process.pid)
            threading.Thread(
                target=self._watch,
                args=(run_id, process),
                daemon=True,
                name=f"watch-{run_id}",
            ).start()
            return run_id

    def _watch(self, run_id: str, process: subprocess.Popen) -> None:
        try:
            return_code = process.wait(timeout=7200)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
            except Exception:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except Exception:
                    pass
            current = self.db.get_run(run_id) or {}
            if current.get("status") not in {"completed", "cancelled", "failed"}:
                self.db.update_run(
                    run_id,
                    status="failed",
                    finished_at=utc_now_iso(),
                    error="任务超过两小时运行时限",
                )
        else:
            current = self.db.get_run(run_id) or {}
            if return_code and current.get("status") not in {"cancelled", "failed"}:
                self.db.update_run(
                    run_id,
                    status="failed",
                    finished_at=utc_now_iso(),
                    error=f"任务进程异常退出，退出码：{return_code}",
                )
        finally:
            with self._lock:
                self._processes.pop(run_id, None)

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            process = self._processes.get(run_id)
            run = self.db.get_run(run_id)
            if not run or run["status"] not in {"queued", "running"}:
                return False
            self.db.update_run(
                run_id,
                status="cancelled",
                finished_at=utc_now_iso(),
                error="已从本机控制台取消",
            )
            if process and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            return True

    def retry(self, run_id: str) -> str:
        run = self.db.get_run(run_id)
        if not run:
            raise KeyError(run_id)
        if run["status"] in {"queued", "running"}:
            return run_id
        return self.start(
            trigger_type="retry",
            fixture=run.get("fixture_path"),
            no_llm=bool(run.get("no_llm")),
        )

    def active_processes(self) -> list[str]:
        with self._lock:
            return [run_id for run_id, proc in self._processes.items() if proc.poll() is None]


class SchedulerService:
    JOB_ID = "daily-frontier-briefing"

    def __init__(self, config: AppConfig, db: Database, manager: JobManager):
        self.config = config
        self.db = db
        self.manager = manager
        self.scheduler = AsyncIOScheduler(timezone=config.tz)

    def _schedule_parts(self) -> tuple[int, int]:
        text = str(self.db.get_setting("schedule", self.config.schedule_text))
        hour, minute = text.split(":", 1)
        return int(hour), int(minute)

    async def _scheduled_run(self) -> None:
        if bool(self.db.get_setting("scheduler_paused", False)):
            return
        self.manager.start(trigger_type="schedule")

    def start(self) -> None:
        hour, minute = self._schedule_parts()
        self.scheduler.add_job(
            self._scheduled_run,
            CronTrigger(hour=hour, minute=minute, timezone=self.config.tz),
            id=self.JOB_ID,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=max(3600, self.config.catchup_hours * 3600),
        )
        self.scheduler.start(paused=bool(self.db.get_setting("scheduler_paused", False)))
        self._maybe_catch_up(hour, minute)

    def _maybe_catch_up(self, hour: int, minute: int) -> None:
        if bool(self.db.get_setting("scheduler_paused", False)):
            return
        now = datetime.now(self.config.tz)
        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now < scheduled or now - scheduled > timedelta(hours=self.config.catchup_hours):
            return
        existing = self.db.edition_for_date(now.date().isoformat())
        if not existing or existing.get("status") not in {"ready", "partial"}:
            self.manager.start(trigger_type="catchup")

    def reschedule(self) -> None:
        hour, minute = self._schedule_parts()
        self.scheduler.reschedule_job(
            self.JOB_ID,
            trigger=CronTrigger(hour=hour, minute=minute, timezone=self.config.tz),
        )

    def pause(self) -> None:
        self.db.set_setting("scheduler_paused", True)
        if self.scheduler.running:
            self.scheduler.pause()

    def resume(self) -> None:
        self.db.set_setting("scheduler_paused", False)
        if self.scheduler.running:
            self.scheduler.resume()

    def status(self) -> dict[str, Any]:
        job = self.scheduler.get_job(self.JOB_ID) if self.scheduler.running else None
        return {
            "running": self.scheduler.running,
            "paused": bool(self.db.get_setting("scheduler_paused", False)),
            "schedule": self.db.get_setting("schedule", self.config.schedule_text),
            "timezone": self.db.get_setting("timezone", self.config.timezone),
            "next_run_time": job.next_run_time.isoformat() if job and job.next_run_time else None,
            "active_workers": self.manager.active_processes(),
        }

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
