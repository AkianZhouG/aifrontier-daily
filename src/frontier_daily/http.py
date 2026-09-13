from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from .security import validate_public_https_url


USER_AGENT = "AIFrontierDaily/0.1 (+local research reader)"


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ValueError(f"来源请求失败（HTTP {response.status_code}）") from exc


@dataclass(frozen=True)
class FetchResult:
    url: str
    content: bytes
    content_type: str
    status_code: int

    def text(self) -> str:
        encoding = "utf-8"
        content_type = self.content_type.lower()
        if "charset=" in content_type:
            candidate = content_type.split("charset=", 1)[1].split(";", 1)[0].strip()
            if candidate:
                encoding = candidate
        try:
            return self.content.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            return self.content.decode("utf-8", errors="replace")


def fetch(url: str, *, timeout: float = 25.0, max_bytes: int = 6_000_000) -> FetchResult:
    current = validate_public_https_url(url)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/atom+xml,application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.4",
    }
    with httpx.Client(timeout=timeout, follow_redirects=False, headers=headers) as client:
        for _ in range(6):
            response = client.get(current)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    _raise_for_status(response)
                current = validate_public_https_url(urljoin(current, location))
                continue
            _raise_for_status(response)
            content = response.content
            if len(content) > max_bytes:
                raise ValueError(f"响应内容超过 {max_bytes} 字节")
            return FetchResult(
                url=str(response.url),
                content=content,
                content_type=response.headers.get("content-type", ""),
                status_code=response.status_code,
            )
    raise ValueError("重定向次数过多")
