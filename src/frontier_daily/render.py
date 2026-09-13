from __future__ import annotations

import html
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .localization import clean_chinese_text, localize_claim_text
from .schemas import EditionDraft, EditionEntry, EditionSynthesis


def _clean_output(value: str) -> str:
    return clean_chinese_text(value)


def _format_edition_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
        return parsed.strftime("%Y年%m月%d日")
    except ValueError:
        return value


def _format_timestamp(value: str | None) -> str:
    if not value:
        return "未记录"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        return parsed.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y年%m月%d日 %H:%M")
    except ValueError:
        return value


def _confidence_label(value: str) -> str:
    return {"high": "高", "medium": "中", "low": "低"}.get(value, value or "未记录")


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def build_draft(
    *,
    edition_date: str,
    events: list[dict],
    synthesis: EditionSynthesis | None,
) -> EditionDraft:
    rewrites = {
        rewrite.event_id: rewrite for rewrite in (synthesis.item_rewrites if synthesis else [])
    }
    entries: list[EditionEntry] = []
    for event in events:
        rewrite = rewrites.get(int(event["id"]))
        entries.append(
            EditionEntry(
                event_id=int(event["id"]),
                item_type=(
                    event["decision"]
                    if event["decision"] in {"new", "update", "focus", "related"}
                    else "update"
                ),
                title=_clean_output(rewrite.title if rewrite else event["title_zh"]),
                summary=_clean_output(rewrite.summary if rewrite else event["summary_zh"]),
                why_it_matters=_clean_output(
                    rewrite.why_it_matters if rewrite else event["why_it_matters_zh"]
                ),
                source_name=event.get("source_name") or "未知来源",
                source_url=event.get("source_url") or "",
                published_at=event.get("published_at"),
                importance=int(event.get("importance") or 0),
                confidence=event.get("confidence") or "medium",
                delta_claims=[localize_claim_text(value) for value in (event.get("delta_claims") or [])],
            )
        )
    overview = (
        synthesis.overview
        if synthesis
        else f"本期收录 {len(entries)} 条首次出现或具有实质增量的人工智能前沿事件。"
    )
    return EditionDraft(
        date=edition_date,
        title=f"人工智能前沿日报 · {_format_edition_date(edition_date)}",
        overview=_clean_output(overview),
        trend_judgment=[_clean_output(value) for value in (synthesis.trend_judgment if synthesis else [])],
        items=entries,
        caveats=(
            [_clean_output(value) for value in synthesis.caveats]
            if synthesis
            else ["本期使用确定性降级摘要，尚未经过模型综合。"]
        ),
    )


def render_markdown(draft: EditionDraft) -> str:
    lines = [f"# {_clean_output(draft.title)}", "", _clean_output(draft.overview), ""]
    item_groups = (
        ("今日新事件", "new"),
        ("重要进展", "update"),
        ("关注主题", "focus"),
        ("相关补充", "related"),
    )
    for heading, item_type in item_groups:
        items = [item for item in draft.items if item.item_type == item_type]
        if not items:
            continue
        lines.extend([f"## {heading}", ""])
        for index, item in enumerate(items, start=1):
            lines.append(f"### {index}. {_clean_output(item.title)}")
            lines.append("")
            lines.append(_clean_output(item.summary))
            if item.delta_claims:
                lines.append("")
                lines.append("新增事实：")
                lines.extend(f"- {localize_claim_text(claim)}" for claim in item.delta_claims)
            if item.why_it_matters:
                lines.extend(["", f"为什么重要：{_clean_output(item.why_it_matters)}"])
            if item.source_url:
                lines.extend(["", f"来源：[{_clean_output(item.source_name)}]({item.source_url})"])
            lines.extend(["", f"发布时间：{_format_timestamp(item.published_at)}"])
            lines.append("")
    if draft.trend_judgment:
        lines.extend(["## 今日判断", ""])
        lines.extend(f"- {_clean_output(value)}" for value in draft.trend_judgment)
        lines.append("")
    if draft.caveats:
        lines.extend(["## 证据说明", ""])
        lines.extend(f"- {_clean_output(value)}" for value in draft.caveats)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_html(draft: EditionDraft) -> str:
    def esc(value: object) -> str:
        return html.escape(str(value or ""), quote=True)

    cards = []
    for item in draft.items:
        badge = {
            "new": "新事件",
            "update": "进展更新",
            "focus": "关注主题",
            "related": "相关补充",
        }.get(item.item_type, "事件")
        badge_class = {"new": "new", "update": "update", "focus": "focus", "related": "related"}.get(
            item.item_type, "update"
        )
        delta = ""
        if item.delta_claims:
            delta_items = "".join(f"<li>{esc(localize_claim_text(claim))}</li>" for claim in item.delta_claims)
            delta = f'<div class="delta"><strong>本次增量</strong><ul>{delta_items}</ul></div>'
        why = (
            f'<p class="why"><strong>为什么重要</strong>{esc(_clean_output(item.why_it_matters))}</p>'
            if item.why_it_matters
            else ""
        )
        source = (
            f'<a class="source" href="{esc(item.source_url)}" target="_blank" rel="noopener noreferrer">{esc(_clean_output(item.source_name))} ↗</a>'
            if item.source_url
            else f'<span class="source">{esc(_clean_output(item.source_name))}</span>'
        )
        cards.append(
            f"""
            <article class="story">
              <div class="story-top">
                <span class="badge {badge_class}">{badge}</span>
                <span class="score">重要度 {item.importance} · 置信度：{esc(_confidence_label(item.confidence))}</span>
              </div>
              <h2>{esc(_clean_output(item.title))}</h2>
              <p class="summary">{esc(_clean_output(item.summary))}</p>
              {delta}
              {why}
              <footer>{source}<span>发布时间：{esc(_format_timestamp(item.published_at))}</span></footer>
            </article>
            """
        )
    trends = "".join(f"<li>{esc(_clean_output(item))}</li>" for item in draft.trend_judgment)
    caveats = "".join(f"<li>{esc(_clean_output(item))}</li>" for item in draft.caveats)
    trend_section = (
        f'<section class="insight"><span class="eyebrow">今日信号</span><h2>今日判断</h2><ul>{trends}</ul></section>'
        if trends
        else ""
    )
    caveat_section = (
        f'<section class="caveats"><h2>证据说明</h2><ul>{caveats}</ul></section>'
        if caveats
        else ""
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(_clean_output(draft.title))}</title>
<style>
:root{{--paper:#f3f0e8;--ink:#171714;--muted:#6d6a61;--line:#d7d1c4;--red:#a43b2d;--green:#315f4a;--amber:#94621c;--blue:#345d78}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font-family:Inter,"PingFang SC","Noto Sans CJK SC",system-ui,sans-serif;line-height:1.65}}
main{{width:min(960px,calc(100% - 32px));margin:0 auto;padding:56px 0 80px}}
header{{display:grid;grid-template-columns:1fr auto;gap:24px;align-items:end;padding-bottom:28px;border-bottom:2px solid var(--ink)}}
.kicker,.eyebrow{{font:700 11px/1.2 ui-monospace,SFMono-Regular,monospace;letter-spacing:.16em;color:var(--red)}}
h1{{font:700 clamp(34px,7vw,72px)/.98 Georgia,"Songti SC",serif;letter-spacing:-.04em;margin:10px 0 0}} .date{{font:600 13px ui-monospace,SFMono-Regular,monospace;color:var(--muted)}}
.lead{{font:400 19px/1.75 Georgia,"Songti SC",serif;max-width:760px;margin:30px 0 42px}}
.stories{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}
.story{{background:rgba(255,255,255,.34);border:1px solid var(--line);padding:24px;display:flex;flex-direction:column;min-height:320px}}
.story-top,footer{{display:flex;justify-content:space-between;gap:16px;align-items:center}} .badge{{font:700 11px ui-monospace,SFMono-Regular,monospace;padding:4px 8px;border:1px solid currentColor}} .badge.new{{color:var(--green)}} .badge.update{{color:var(--amber)}} .badge.focus{{color:var(--blue)}} .badge.related{{color:var(--muted)}}
.score,footer{{font-size:12px;color:var(--muted)}} h2{{font:700 24px/1.25 Georgia,"Songti SC",serif;margin:18px 0 12px}} .summary{{margin:0 0 16px}}
.delta{{border-left:3px solid var(--amber);padding:8px 12px;margin:4px 0 16px;background:rgba(148,98,28,.06)}} .delta ul,.insight ul,.caveats ul{{margin:6px 0 0;padding-left:20px}}
.why{{margin:0 0 20px;color:#3d3b35}} .why strong{{display:block;font:700 11px ui-monospace,SFMono-Regular,monospace;letter-spacing:.1em;color:var(--red);margin-bottom:4px}}
footer{{margin-top:auto;padding-top:18px;border-top:1px solid var(--line)}} .source{{color:var(--ink);font-weight:650;text-decoration:none}}
.insight{{margin-top:38px;padding:30px;border-top:2px solid var(--ink);border-bottom:1px solid var(--line)}} .insight h2,.caveats h2{{margin:8px 0 12px}}
.caveats{{margin-top:30px;color:var(--muted)}}
@media(max-width:720px){{header{{grid-template-columns:1fr}}.stories{{grid-template-columns:1fr}}.story{{min-height:0}}main{{padding-top:32px}}}}
</style>
</head>
<body><main>
<header><div><span class="kicker">人工智能前沿日报</span><h1>人工智能前沿日报</h1></div><div class="date">{esc(_format_edition_date(draft.date))}</div></header>
<p class="lead">{esc(_clean_output(draft.overview))}</p>
<section class="stories">{''.join(cards) or '<p>本期没有达到收录阈值的新事件。</p>'}</section>
{trend_section}{caveat_section}
</main></body></html>"""


def write_edition(root: Path, draft: EditionDraft) -> dict[str, Path]:
    localized = draft.model_copy(deep=True)
    localized.title = _clean_output(localized.title)
    localized.overview = _clean_output(localized.overview)
    localized.trend_judgment = [_clean_output(value) for value in localized.trend_judgment]
    localized.caveats = [_clean_output(value) for value in localized.caveats]
    for item in localized.items:
        item.title = _clean_output(item.title)
        item.summary = _clean_output(item.summary)
        item.why_it_matters = _clean_output(item.why_it_matters)
        item.source_name = _clean_output(item.source_name)
        item.delta_claims = [localize_claim_text(value) for value in item.delta_claims]

    edition_dir = root / localized.date
    json_path = edition_dir / "edition.json"
    markdown_path = edition_dir / "report.md"
    html_path = edition_dir / "report.html"
    _atomic_text(json_path, localized.model_dump_json(indent=2) + "\n")
    _atomic_text(markdown_path, render_markdown(localized))
    _atomic_text(html_path, render_html(localized))
    return {"json": json_path, "markdown": markdown_path, "html": html_path}
