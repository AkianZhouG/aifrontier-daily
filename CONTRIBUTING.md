# Contributing

[English](CONTRIBUTING.md) | [Chinese](CONTRIBUTING.zh-CN.md)

Thank you for your interest in AI Frontier Daily. The project currently focuses on Chinese daily briefings and a macOS local-first experience. Contributions are welcome for bug fixes, tests, source adapters, quality rules, and documentation.

## Development environment

- Python 3.11 or newer
- Node.js compatible with the current frontend toolchain
- macOS is the supported platform for service-installation scripts; other Unix systems should run the service manually

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cd frontend
npm ci
npm run build
cd ..
```

## Local verification

Run at least the following before submitting a change:

```bash
.venv/bin/python -m compileall -q src
.venv/bin/pytest
cd frontend && npm run build
```

The deterministic fixture run does not require a model or external network access:

```bash
FRONTIER_LLM_ENABLED=0 \
  .venv/bin/frontier-daily run \
  --fixture tests/fixtures/frontier-items.json \
  --no-llm
```

## Changes

- Keep each commit focused on one problem and describe behavior changes in the commit message.
- Add or update tests and documentation when changing collectors, quality rules, or deduplication behavior.
- Do not commit `config/app.json`, `data/`, `logs/`, databases, model credentials, API keys, or generated fetch artifacts.
- Do not place real private articles, company-internal material, or content requiring authorization in test fixtures.
- For changes involving security boundaries, source requests, subprocesses, or configuration paths, describe the threat model and verification steps in the pull request.

## Pull requests

A pull request should describe:

1. The problem being solved and the relevant design trade-offs;
2. Configuration, database, or user-behavior changes;
3. Test commands and their results;
4. Source terms, rate limits, and failure handling when external sources are involved.

Never paste secrets, credential files, private URLs, complete runtime logs, or personal data into a public issue or pull request.
