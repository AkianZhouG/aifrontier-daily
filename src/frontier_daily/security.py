from __future__ import annotations

import ipaddress
import os
import socket
from pathlib import Path
from urllib.parse import urlparse


class UnsafeURL(ValueError):
    pass


def validate_public_https_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise UnsafeURL("仅允许使用 HTTPS 地址")
    if parsed.username or parsed.password:
        raise UnsafeURL("地址中不允许包含账号或密码")
    host = (parsed.hostname or "").strip().lower()
    if not host or host == "localhost" or host.endswith(".localhost"):
        raise UnsafeURL("主机名缺失或指向本机地址")
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURL(f"主机名解析失败：{host}") from exc
    if not infos:
        raise UnsafeURL(f"未找到主机地址：{host}")
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise UnsafeURL(f"主机名解析到了非公网地址：{host}")
    return url


def minimal_subprocess_env(*, extra: dict[str, str] | None = None) -> dict[str, str]:
    allowed = {
        "HOME",
        "USER",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "PATH",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "PI_CODING_AGENT_DIR",
        "PI_PACKAGE_DIR",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "OPENROUTER_API_KEY",
        "DEEPSEEK_API_KEY",
        "GROQ_API_KEY",
        "CEREBRAS_API_KEY",
        "XAI_API_KEY",
        "FIREWORKS_API_KEY",
        "TOGETHER_API_KEY",
        "ZAI_API_KEY",
        "MINIMAX_API_KEY",
        "MOONSHOT_API_KEY",
        "KIMI_API_KEY",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed and value}
    env.setdefault("HOME", str(Path.home()))
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin")
    env.setdefault("LANG", "en_US.UTF-8")
    env["PI_SKIP_VERSION_CHECK"] = "1"
    env["PI_TELEMETRY"] = "0"
    if extra:
        env.update({key: value for key, value in extra.items() if value is not None})
    return env
