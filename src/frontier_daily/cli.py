from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .config import install_local_config, load_config
from .db import open_database
from .worker import main as worker_main


def command_init() -> int:
    config = load_config()
    local = install_local_config(config)
    db = open_database(config)
    print(f"已初始化项目：{config.root}")
    print(f"本地配置：    {local}")
    print(f"数据库：      {config.db_path}")
    print(f"来源数量：    {len(db.list_sources())}")
    return 0


def command_status() -> int:
    config = load_config()
    db = open_database(config)
    payload = db.dashboard()
    payload["settings"] = {
        "schedule": db.get_setting("schedule", config.schedule_text),
        "timezone": db.get_setting("timezone", config.timezone),
        "scheduler_paused": db.get_setting("scheduler_paused", False),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_doctor() -> int:
    config = load_config()
    db = open_database(config)
    agent_binary = str(db.get_setting("agent_binary", config.pi_binary))
    checks = {
        "python": sys.version.split()[0],
        "agent_binary": shutil.which(agent_binary) or (
            agent_binary if Path(agent_binary).is_file() else None
        ),
        "frontend_built": (config.frontend_dist / "index.html").is_file(),
        "database_writable": config.db_path.exists(),
        "enabled_sources": len(db.list_sources(enabled_only=True)),
        "host_is_local": config.host in {"127.0.0.1", "localhost"},
    }
    ok = all(value not in {None, False, 0} for value in checks.values())
    print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def command_serve() -> int:
    config = load_config()
    if config.host not in {"127.0.0.1", "localhost"}:
        print("拒绝绑定非本机地址，请将 host 设置为 127.0.0.1", file=sys.stderr)
        return 2
    import uvicorn

    uvicorn.run(
        "frontier_daily.api:app",
        host=config.host,
        port=config.port,
        workers=1,
        access_log=False,
        log_level="info",
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="frontier-daily", description="人工智能前沿日报本机控制命令")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="初始化本地配置、数据库和来源")
    subparsers.add_parser("serve", help="运行本机控制服务")
    subparsers.add_parser("status", help="查看持久化服务状态")
    subparsers.add_parser("doctor", help="检查本机运行条件")
    run_parser = subparsers.add_parser("run", help="同步运行一轮日报流水线")
    run_parser.add_argument("--fixture")
    run_parser.add_argument("--no-llm", action="store_true")
    run_parser.add_argument("--trigger", default="manual-cli")

    args = parser.parse_args(argv)
    if args.command == "init":
        return command_init()
    if args.command == "serve":
        return command_serve()
    if args.command == "status":
        return command_status()
    if args.command == "doctor":
        return command_doctor()
    if args.command == "run":
        worker_args = ["--trigger", args.trigger]
        if args.fixture:
            worker_args += ["--fixture", args.fixture]
        if args.no_llm:
            worker_args.append("--no-llm")
        return worker_main(worker_args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
