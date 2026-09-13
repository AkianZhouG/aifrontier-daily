# Security Policy

[English](SECURITY.md) | [Chinese](SECURITY.zh-CN.md)

## Scope

AI Frontier Daily binds to a local address by default, fetches external webpages, writes to a local database, and can invoke an agent configured by the user. It is intended for personal local use and should not be deployed to the public Internet without additional authentication, access control, and isolation.

Pi's no-tool flags narrow the permission boundary, but Pi itself is not a sandbox. Configure only agent executables and model providers that you trust.

## Reporting a vulnerability

Please do not disclose an unpatched security issue in a public issue, discussion, or pull request.

- If the repository is hosted on GitHub, use Private Vulnerability Reporting or a Security Advisory.
- If it is hosted elsewhere, contact the maintainer through a private channel provided by the repository owner.
- Include the affected version, reproduction steps, impact, and suggested remediation.
- Remove keys, credential files, private URLs, complete logs, and personal data. Redact any sample that must be included.

Areas of particular interest include:

- SSRF, redirect, and external-source request bypasses;
- remote access to the local service or cross-site control;
- arbitrary command execution, unsafe subprocesses, and path traversal;
- prompt injection that crosses the model's permission boundary;
- sensitive information leakage through logs, databases, and generated artifacts.
