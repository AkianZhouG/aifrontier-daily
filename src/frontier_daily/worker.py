from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

from .config import load_config
from .db import open_database
from .pipeline import Pipeline
from .schemas import utc_now_iso


class WorkerCancelled(KeyboardInterrupt):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行一轮人工智能前沿日报流水线")
    parser.add_argument("--run-id")
    parser.add_argument("--fixture")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--trigger", default="manual")
    args = parser.parse_args(argv)

    config = load_config()
    db = open_database(config)
    edition_date = datetime.now(config.tz).date().isoformat()
    run_id = args.run_id
    if not run_id:
        active = db.active_run()
        if active:
            print(f"已有运行任务正在执行：{active['run_id']}", file=sys.stderr)
            return 3
        log_path = config.logs_dir / f"run-{datetime.now(config.tz):%Y%m%d-%H%M%S}.jsonl"
        run_id = db.create_run(
            trigger_type=args.trigger,
            edition_date=edition_date,
            log_path=log_path,
            fixture_path=args.fixture,
            no_llm=args.no_llm,
        )

    def cancel(_sig, _frame):
        db.update_run(
            run_id,
            status="cancelled",
            finished_at=utc_now_iso(),
            error="任务已被系统信号取消",
        )
        raise WorkerCancelled()

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)

    try:
        result = Pipeline(config, db, run_id).run_pipeline()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except WorkerCancelled:
        print("日报任务已取消", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"日报任务失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
