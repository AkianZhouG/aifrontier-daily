from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .http import fetch



TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
    "spm",
}


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()
    port = parts.port
    netloc = hostname
    if port and not (scheme == "https" and port == 443):
        netloc = f"{hostname}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lower = key.lower()
        if lower.startswith("utm_") or lower in TRACKING_PARAMS:
            continue
        query.append((key, value))
    query.sort()
    return urlunsplit((scheme, netloc, path, urlencode(query, doseq=True), ""))


def normalize_text(text: str) -> str:
    return " ".join(html.unescape(text or "").lower().split())


class _ArticleParser(HTMLParser):
    BLOCKED = {"script", "style", "noscript", "svg", "nav", "footer", "form", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocked_depth = 0
        self.article_depth = 0
        self.body_depth = 0
        self.in_title = False
        self.title_parts: list[str] = []
        self.article_parts: list[str] = []
        self.body_parts: list[str] = []
        self.description = ""
        self.published_at = ""

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        if tag in self.BLOCKED:
            self.blocked_depth += 1
        if tag in {"article", "main"}:
            self.article_depth += 1
        if tag == "body":
            self.body_depth += 1
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            key = (values.get("name") or values.get("property") or "").lower()
            content = values.get("content", "").strip()
            if key in {"description", "og:description"} and not self.description:
                self.description = content
            if key in {
                "article:published_time",
                "date",
                "datepublished",
                "publishdate",
                "pub_date",
            } and not self.published_at:
                self.published_at = content
        if tag in {"p", "div", "section", "h1", "h2", "h3", "li", "br"}:
            self._append("\n")

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag == "title":
            self.in_title = False
        if tag in {"article", "main"} and self.article_depth:
            self.article_depth -= 1
        if tag == "body" and self.body_depth:
            self.body_depth -= 1
        if tag in self.BLOCKED and self.blocked_depth:
            self.blocked_depth -= 1
        if tag in {"p", "div", "section", "h1", "h2", "h3", "li"}:
            self._append("\n")

    def handle_data(self, data: str):
        if self.blocked_depth:
            return
        if self.in_title:
            self.title_parts.append(data)
        self._append(data)

    def _append(self, value: str):
        if self.blocked_depth:
            return
        if self.article_depth:
            self.article_parts.append(value)
        if self.body_depth:
            self.body_parts.append(value)


def _clean_lines(parts: list[str]) -> str:
    lines = []
    previous = ""
    for line in "".join(parts).splitlines():
        value = " ".join(line.split())
        if not value or value == previous:
            continue
        previous = value
        lines.append(value)
    return "\n".join(lines)


def extract_html(html_text: str, *, max_chars: int) -> dict[str, str]:
    parser = _ArticleParser()
    parser.feed(html_text)
    article = _clean_lines(parser.article_parts)
    body = article if len(article) >= 200 else _clean_lines(parser.body_parts)
    title = " ".join("".join(parser.title_parts).split())
    return {
        "title": title[:500],
        "description": " ".join(parser.description.split())[:2000],
        "published_at": parser.published_at[:100],
        "content": body[:max_chars],
    }


def fetch_page_content(url: str, *, max_chars: int) -> tuple[str, dict[str, str]]:
    result = fetch(url)
    content_type = result.content_type.lower()
    if "pdf" in content_type or result.url.lower().endswith(".pdf"):
        return result.url, {
            "title": "",
            "description": "PDF source",
            "published_at": "",
            "content": "",
        }
    return result.url, extract_html(result.text(), max_chars=max_chars)
