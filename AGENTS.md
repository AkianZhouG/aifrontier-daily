# AI Frontier Daily Agent Guide

[English](AGENTS.md) | [Chinese](AGENTS.zh-CN.md)

## Project

AI Frontier Daily is a local-first macOS application that discovers primary-source AI news, extracts structured events, deduplicates across days, and produces a Chinese daily briefing. Its read, research, and write workflow is implemented in this repository.

## Architecture

- `src/frontier_daily/collectors/`: deterministic RSS/Atom/sitemap/GitHub/fixture discovery and local HTML extraction.
- `src/frontier_daily/db.py`: SQLite schema and transactions. SQLite is the source of truth for source items, events, claims, editions, and job runs.
- `src/frontier_daily/pipeline.py`: one-shot pipeline orchestration.
- `src/frontier_daily/llm.py`: constrained, no-tool agent invocation. Fetched pages are untrusted data.
- `src/frontier_daily/api.py`: local-only FastAPI control plane and static frontend host.
- `src/frontier_daily/scheduler.py`: APScheduler and worker subprocess ownership.
- `frontend/`: Vue management UI. Production serves `frontend/dist` from FastAPI; Vite is development-only.
- `scripts/briefingctl`: launchd and service lifecycle CLI.

## Invariants

- launchd owns process liveness; APScheduler owns the daily schedule; SQLite owns durable state; the UI only sends control intents.
- Only one pipeline worker may run at a time. Re-runs for the same edition date are idempotent.
- Deduplicate events, not only URLs. Existing events reappear only when they gain material claims.
- Search results are discovery hints. Published claims must retain a primary source or be labeled lower-confidence.
- Every production candidate passes the deterministic source quality policy before model extraction, and every extracted event passes its source-tier importance floor. Community/media items require a current quality assessment; policy changes request an edition rebuild.
- Never mark an edition ready until its JSON and HTML artifacts exist and the database transaction commits.
- Never substitute yesterday's report when today's run fails.
- Bind production HTTP only to `127.0.0.1`. Do not add wildcard CORS.
- Mutating endpoints require same-origin CSRF validation. Do not add arbitrary command execution endpoints.
- The configured agent runs unattended with no tools, no extensions, no skills, no context files, and no default resource discovery. It receives a bounded source bundle and returns JSON on stdout.
- Do not log secrets, auth files, raw environment variables, or full private URLs.
- Write generated artifacts through a sibling temporary file followed by `os.replace`.

## Commands

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cd frontend && npm ci && npm run build
cd .. && .venv/bin/pytest
.venv/bin/frontier-daily init
.venv/bin/frontier-daily run --fixture tests/fixtures/frontier-items.json --no-llm
.venv/bin/frontier-daily serve
```

## Verification

Before meaningful changes:

```bash
.venv/bin/python -m compileall -q src
.venv/bin/pytest
cd frontend && npm run build
```

For scheduler or launchd changes, also run `scripts/briefingctl status` and verify no duplicate worker process exists.
