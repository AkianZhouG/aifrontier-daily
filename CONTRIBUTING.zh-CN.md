# 贡献指南

[English](CONTRIBUTING.md) | [简体中文](CONTRIBUTING.zh-CN.md)

感谢关注 AI Frontier Daily。项目目前以中文日报和 macOS 本机运行体验为主，欢迎提交修复、测试、来源适配和文档改进。

## 开发环境

- Python 3.11 或更高版本
- Node.js 需要能够运行当前前端工具链
- macOS 是服务安装脚本的正式支持平台；其他 Unix 系统请手动运行服务

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cd frontend
npm ci
npm run build
cd ..
```

## 本地验证

提交前至少运行：

```bash
.venv/bin/python -m compileall -q src
.venv/bin/pytest
cd frontend && npm run build
```

不需要模型或外网即可运行确定性测试样例：

```bash
FRONTIER_LLM_ENABLED=0 \
  .venv/bin/frontier-daily run \
  --fixture tests/fixtures/frontier-items.json \
  --no-llm
```

## 提交变更

- 一个提交尽量只解决一个问题，并在提交说明中说明行为变化。
- 新增采集器、质量规则或去重规则时，应同步增加测试和文档。
- 不要提交 `config/app.json`、`data/`、`logs/`、数据库、模型认证文件、API 密钥或抓取生成物。
- 不要把真实的私有文章、公司内部材料或需要授权的内容放入测试样例。
- 涉及安全边界、来源请求、子进程或配置路径的改动，应在 PR 描述中说明威胁模型和验证方式。

## Pull Request

PR 描述建议包含：

1. 要解决的问题和设计取舍；
2. 影响的配置、数据库或用户行为；
3. 执行过的测试命令及结果；
4. 如果涉及外部来源，说明来源条款、速率限制和失败处理。

请不要在公开 Issue 或 PR 中粘贴密钥、认证文件、私有 URL、完整运行日志或个人数据。
