# AI Frontier Daily Agent Guide（中文）

[English](AGENTS.md) | [简体中文](AGENTS.zh-CN.md)

## 项目

AI Frontier Daily 是一个本机优先的 macOS 应用，用于发现人工智能一手资讯、提取结构化事件、跨天去重并生成中文日报。读取、研究和写作流程由本仓库自身实现。

## 架构

- `src/frontier_daily/collectors/`：确定性的 RSS、Atom、网站地图、GitHub、测试样例采集器和本地 HTML 提取。
- `src/frontier_daily/db.py`：SQLite 模式和事务。SQLite 是来源材料、事件、事实、日报和运行记录的事实源。
- `src/frontier_daily/pipeline.py`：单次流水线编排。
- `src/frontier_daily/llm.py`：受约束、无工具的智能代理调用。抓取页面都是不可信数据。
- `src/frontier_daily/api.py`：仅限本机的 FastAPI 控制面和静态前端托管。
- `src/frontier_daily/scheduler.py`：APScheduler 和 Worker 子进程管理。
- `frontend/`：Vue 管理界面。生产环境由 FastAPI 托管 `frontend/dist`；Vite 仅用于开发。
- `scripts/briefingctl`：launchd 和服务生命周期命令行工具。

## 不变量

- launchd 负责进程存活；APScheduler 负责日报时间；SQLite 负责持久化状态；页面只发送控制意图。
- 同一时间只能运行一个流水线 Worker。同一日报日期的重跑必须幂等。
- 去重对象是事件，而不只是 URL。只有获得实质性事实增量的已有事件才会再次出现。
- 搜索结果只是发现线索。已发布的事实必须保留一手来源，或明确标注较低置信度。
- 每份生产候选材料必须先通过确定性来源质量策略，再交给模型提取；每个提取事件还必须通过其来源等级的重要度门槛。社区和媒体材料必须有当前质量评估；质量策略变化需要重新整理日报。
- 只有 JSON 和 HTML 产物已经存在且数据库事务提交后，才能将日报标记为已就绪。
- 当天运行失败时，不能用昨天的日报替代今天的日报。
- 生产 HTTP 只能绑定 `127.0.0.1`。不要添加通配符 CORS。
- 写接口必须进行同源 CSRF 校验。不要添加任意命令执行接口。
- 配置的智能代理以无人值守方式运行，不启用工具、扩展、技能、上下文文件或默认资源发现。它只接收有界的来源材料包，并通过 stdout 返回 JSON。
- 不要记录密钥、认证文件、原始环境变量或完整的私有 URL。
- 生成的产物必须先写入同目录临时文件，再通过 `os.replace` 原子替换。

## 命令

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cd frontend && npm ci && npm run build
cd .. && .venv/bin/pytest
.venv/bin/frontier-daily init
.venv/bin/frontier-daily run --fixture tests/fixtures/frontier-items.json --no-llm
.venv/bin/frontier-daily serve
```

## 验证

进行有意义的改动前：

```bash
.venv/bin/python -m compileall -q src
.venv/bin/pytest
cd frontend && npm run build
```

如果改动调度器或 launchd，还要运行 `scripts/briefingctl status`，并确认没有重复的 Worker 进程。
