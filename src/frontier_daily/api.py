from __future__ import annotations

import asyncio
import hmac
import json
import os
import secrets
import shutil
import subprocess
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .config import AppConfig, load_config
from .db import Database, open_database
from .scheduler import JobManager, SchedulerService
from .schemas import EventAction, RunRequest, RuntimeSettings


MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _resolve_agent_binary(value: str) -> str:
    candidate_text = str(value or "").strip()
    if not candidate_text or "\x00" in candidate_text:
        raise ValueError("本地智能代理工具路径不能为空")
    found = shutil.which(candidate_text)
    if found:
        return str(Path(found).resolve())
    candidate = Path(candidate_text).expanduser()
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate.resolve())
    raise ValueError(f"找不到可执行的本地智能代理工具：{candidate_text}")


class LocalControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in MUTATING_METHODS and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin", "")
            parsed = urlparse(origin) if origin else None
            if not parsed or parsed.hostname not in {"127.0.0.1", "localhost", "testserver"}:
                return JSONResponse({"detail": "必须使用本机同源请求"}, status_code=403)
            expected = getattr(request.app.state, "csrf_token", "")
            header = request.headers.get("x-frontier-csrf", "")
            cookie = request.cookies.get("frontier_csrf", "")
            if not expected or not hmac.compare_digest(header, expected) or not hmac.compare_digest(cookie, expected):
                return JSONResponse({"detail": "控制请求校验失败，请刷新页面后重试"}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src 'self'",
        )
        return response


def _git_sha(root: Path) -> str:
    try:
        process = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return process.stdout.strip() if process.returncode == 0 else "uncommitted"
    except Exception:
        return "uncommitted" if (root / ".git").exists() else "unknown"


def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or load_config()
    db = open_database(config)
    manager = JobManager(config, db)
    scheduler = SchedulerService(config, db, manager)
    started_at = datetime.now(config.tz).isoformat(timespec="seconds")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        recovered = db.recover_stale_runs()
        app.state.recovered_runs = recovered
        scheduler.start()
        yield
        scheduler.shutdown()

    app = FastAPI(
        title="人工智能前沿日报",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.config = config
    app.state.db = db
    app.state.manager = manager
    app.state.scheduler = scheduler
    app.state.csrf_token = secrets.token_urlsafe(32)
    app.state.started_at = started_at
    app.state.git_sha = _git_sha(config.root)
    app.add_middleware(LocalControlMiddleware)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "version": __version__,
            "git_sha": app.state.git_sha,
            "started_at": started_at,
            "database": str(config.db_path),
        }

    @app.get("/api/session")
    def session(response: Response):
        response.set_cookie(
            "frontier_csrf",
            app.state.csrf_token,
            httponly=True,
            samesite="strict",
            secure=False,
            path="/",
        )
        return {"csrf_token": app.state.csrf_token}

    def agent_settings_payload() -> dict:
        return {
            "binary": db.get_setting("agent_binary", config.pi_binary),
            "provider": db.get_setting("agent_provider", config.pi_provider),
            "model": db.get_setting("agent_model", config.pi_model),
            "thinking": db.get_setting("agent_thinking", config.pi_thinking),
        }

    @app.get("/api/dashboard")
    def dashboard():
        data = db.dashboard()
        data["scheduler"] = scheduler.status()
        data["agent"] = agent_settings_payload()
        data["service"] = {
            "version": __version__,
            "git_sha": app.state.git_sha,
            "started_at": started_at,
            "recovered_runs": getattr(app.state, "recovered_runs", 0),
        }
        return data

    @app.get("/api/runs")
    def runs(limit: int = 30):
        return db.list_runs(limit=min(max(limit, 1), 100))

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str):
        run = db.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="未找到运行记录")
        return run

    @app.post("/api/runs")
    def run_now(payload: RunRequest):
        fixture = None
        if payload.fixture:
            fixture_path = Path(payload.fixture).expanduser().resolve()
            try:
                fixture_path.relative_to(config.root)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="测试样例必须位于项目目录内") from exc
            if not fixture_path.is_file():
                raise HTTPException(status_code=400, detail="测试样例不存在")
            fixture = str(fixture_path)
        run_id = manager.start(trigger_type="manual", fixture=fixture, no_llm=payload.no_llm)
        return db.get_run(run_id)

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: str):
        if not manager.cancel(run_id):
            raise HTTPException(status_code=409, detail="运行任务当前未处于活动状态")
        return db.get_run(run_id)

    @app.post("/api/runs/{run_id}/retry")
    def retry_run(run_id: str):
        try:
            new_id = manager.retry(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="未找到运行记录") from exc
        return db.get_run(new_id)

    @app.get("/api/runs/{run_id}/logs")
    def run_logs(run_id: str, offset: int = 0):
        run = db.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="未找到运行记录")
        path = Path(run["log_path"])
        if not path.exists():
            return {"offset": 0, "next_offset": 0, "text": ""}
        size = path.stat().st_size
        offset = min(max(offset, 0), size)
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read(128_000)
        return {
            "offset": offset,
            "next_offset": offset + len(data),
            "text": data.decode("utf-8", errors="replace"),
        }

    @app.get("/api/events")
    def events(limit: int = 100, status: str | None = None):
        return db.list_events(limit=min(max(limit, 1), 300), status=status)

    @app.post("/api/events/{event_id}/action")
    def event_action(event_id: int, payload: EventAction):
        if not db.event_action(event_id, payload.action):
            raise HTTPException(status_code=404, detail="未找到事件，或事件操作无效")
        return {"ok": True, "event_id": event_id, "action": payload.action}

    @app.get("/api/editions")
    def editions(limit: int = 30):
        return db.list_editions(limit=min(max(limit, 1), 100))

    @app.get("/api/editions/{edition_date}")
    def edition(edition_date: str):
        value = db.edition_for_date(edition_date)
        if not value:
            raise HTTPException(status_code=404, detail="未找到该期日报")
        return value

    @app.get("/api/editions/{edition_date}/report")
    def edition_report(edition_date: str):
        value = db.edition_for_date(edition_date)
        if not value or not value.get("html_path"):
            raise HTTPException(status_code=404, detail="未找到日报")
        path = Path(value["html_path"])
        if not path.is_file():
            raise HTTPException(status_code=404, detail="日报文件不存在")
        response = FileResponse(path, media_type="text/html")
        # A rerun replaces the same date's artifact. Do not let a browser keep
        # displaying the pre-rerun report from its HTTP cache.
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/sources")
    def sources():
        return db.list_sources()

    @app.patch("/api/sources/{source_id}")
    async def source_enabled(source_id: str, request: Request):
        body = await request.json()
        if "enabled" not in body or not isinstance(body["enabled"], bool):
            raise HTTPException(status_code=400, detail="启用状态必须是布尔值")
        if not db.set_source_enabled(source_id, body["enabled"]):
            raise HTTPException(status_code=404, detail="未找到来源")
        return {"ok": True, "source_id": source_id, "enabled": body["enabled"]}

    def runtime_settings_payload() -> dict:
        return {
            "schedule": db.get_setting("schedule", config.schedule_text),
            "timezone": db.get_setting("timezone", config.timezone),
            "max_items": db.get_setting("max_items", config.max_items),
            "lookback_hours": db.get_setting("lookback_hours", config.lookback_hours),
            "scheduler_paused": db.get_setting("scheduler_paused", False),
            "agent_binary": db.get_setting("agent_binary", config.pi_binary),
            "agent_provider": db.get_setting("agent_provider", config.pi_provider),
            "agent_model": db.get_setting("agent_model", config.pi_model),
            "agent_thinking": db.get_setting("agent_thinking", config.pi_thinking),
            "focus_profile": db.get_setting("focus_profile", config.focus_profile),
            "report_rebuild_requested": bool(
                db.get_setting("report_rebuild_requested", False)
            ),
        }

    @app.get("/api/settings")
    def settings():
        return runtime_settings_payload()

    @app.put("/api/settings")
    def update_settings(payload: RuntimeSettings):
        try:
            ZoneInfo(payload.timezone)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="时区无效") from exc
        if payload.timezone != config.timezone:
            raise HTTPException(
                status_code=409,
                detail="修改时区需要编辑 config/app.json 并重启服务",
            )

        current = runtime_settings_payload()
        agent_binary = (payload.agent_binary or current["agent_binary"]).strip()
        agent_provider = (payload.agent_provider or current["agent_provider"]).strip()
        agent_model = (payload.agent_model or current["agent_model"]).strip()
        agent_thinking = (payload.agent_thinking or current["agent_thinking"]).strip()
        if config.llm_enabled and (not agent_provider or not agent_model or not agent_thinking):
            raise HTTPException(status_code=400, detail="启用智能代理时，提供方、模型和思考级别不能为空")
        focus_profile = (
            payload.focus_profile
            if payload.focus_profile is not None
            else current["focus_profile"]
        )
        try:
            if config.llm_enabled:
                agent_binary = _resolve_agent_binary(agent_binary)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        new_values = {
            "agent_binary": agent_binary,
            "agent_provider": agent_provider,
            "agent_model": agent_model,
            "agent_thinking": agent_thinking,
            "focus_profile": (focus_profile or "").strip(),
        }
        rebuild_keys = tuple(new_values)
        changed = (
            any(new_values[key] != current.get(key) for key in rebuild_keys)
            or payload.max_items != current["max_items"]
        )
        db.set_setting("schedule", payload.schedule)
        db.set_setting("timezone", payload.timezone)
        db.set_setting("max_items", payload.max_items)
        db.set_setting("lookback_hours", payload.lookback_hours)
        for key, value in new_values.items():
            db.set_setting(key, value)
        if changed:
            db.set_setting("report_rebuild_requested", True)
        if payload.scheduler_paused:
            scheduler.pause()
        else:
            scheduler.resume()
        scheduler.reschedule()
        return settings()

    @app.post("/api/scheduler/pause")
    def pause_scheduler():
        scheduler.pause()
        return scheduler.status()

    @app.post("/api/scheduler/resume")
    def resume_scheduler():
        scheduler.resume()
        scheduler.reschedule()
        return scheduler.status()

    async def stream_events(request: Request) -> AsyncIterator[str]:
        counter = 0
        while True:
            if await request.is_disconnected():
                break
            dashboard_data = db.dashboard()
            dashboard_data["agent"] = agent_settings_payload()
            payload = {
                "id": counter,
                "dashboard": dashboard_data,
                "scheduler": scheduler.status(),
                "runs": db.list_runs(limit=10),
            }
            yield f"id: {counter}\nevent: state\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            counter += 1
            await asyncio.sleep(2)

    @app.get("/api/stream")
    async def stream(request: Request):
        return StreamingResponse(stream_events(request), media_type="text/event-stream")

    assets = config.frontend_dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="未找到请求资源")
        index = config.frontend_dist / "index.html"
        if index.is_file():
            return FileResponse(index, media_type="text/html")
        return HTMLResponse(
            "<h1>人工智能前沿日报</h1><p>管理页面尚未构建，请运行 <code>cd frontend &amp;&amp; npm run build</code>。</p>",
            status_code=503,
        )

    return app


app = create_app()
