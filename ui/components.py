"""Presentational building blocks. Each helper returns an HTML string."""

from __future__ import annotations

import html
from typing import Any, Iterable

from . import theme


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def pill(status: str, *, small: bool = False) -> str:
    tone = theme.status_tone(status)
    color = theme.tone_color(tone)
    klass = "cnc-pill sm" if small else "cnc-pill"
    return (
        f'<span class="{klass}" style="color:{color}">'
        f'<span class="dot"></span>{esc(theme.status_label(status))}</span>'
    )


def pill_text(label: str, tone: str, *, small: bool = False) -> str:
    color = theme.tone_color(tone)
    klass = "cnc-pill sm" if small else "cnc-pill"
    return f'<span class="{klass}" style="color:{color}"><span class="dot"></span>{esc(label)}</span>'


def topbar(*, api_configured: bool, meta: str) -> str:
    api = (
        '<span style="color:#46A87A">AI READY</span>'
        if api_configured
        else '<span style="color:#E0A03C">AI KEY MISSING</span>'
    )
    return (
        '<div class="cnc-topbar">'
        '<div class="cnc-brand">'
        '<span class="mark">CNC</span>'
        '<span class="name">CNC Part Analyzer</span>'
        '</div>'
        f'<div class="cnc-topbar-meta"><span>{meta}</span><span>{api}</span></div>'
        '</div>'
    )


def section_label(text: str) -> str:
    return f'<div class="cnc-section-label">{esc(text)}</div>'


def source_card(title: str, status: str, lines: Iterable[str], *, accent_status: str | None = None) -> str:
    color = theme.status_color(accent_status or status)
    body = "<br>".join(line for line in lines) or '<span class="cnc-muted">Not supplied</span>'
    return (
        f'<div class="cnc-card" style="border-left-color:{color}">'
        f'<div class="card-head"><span class="card-title">{esc(title)}</span>{pill(status, small=True)}</div>'
        f'<div class="card-line">{body}</div>'
        '</div>'
    )


def kv(key: str, value: str, *, tone: str | None = None) -> str:
    color = theme.tone_color(tone) if tone else "var(--cnc-text)"
    return (
        f'<div class="cnc-kv"><span class="k">{esc(key)}</span>'
        f'<span class="v" style="color:{color}">{value}</span></div>'
    )


def finding_row(status: str, summary: str, check: str) -> str:
    return (
        '<div class="cnc-finding">'
        f'{pill(status, small=True)}'
        f'<div class="ft">{esc(summary)}<span class="fc">{esc(check)}</span></div>'
        '</div>'
    )


def callout(tone: str, lead: str, body: str) -> str:
    color = theme.tone_color(tone)
    return (
        f'<div class="cnc-callout" style="border-left-color:{color};'
        f'background:color-mix(in srgb, {color} 9%, transparent)">'
        f'<span class="lead" style="color:{color}">{esc(lead)}</span>{esc(body)}</div>'
    )


def part_head(part: str, status: str | None, coverage: str) -> str:
    right = pill(status) if status else ""
    return (
        '<div class="cnc-part-head">'
        '<div><span class="cnc-part-id"><span class="lbl">PART</span>'
        f'{esc(part)}</span></div>'
        f'<div style="text-align:right;display:flex;align-items:center;gap:14px">'
        f'<span class="cnc-mono cnc-dim" style="font-size:10.5px;letter-spacing:.1em">{esc(coverage)}</span>'
        f'{right}</div>'
        '</div>'
    )


def evidence_row(location: str, text: str) -> str:
    return (
        f'<div class="cnc-evidence-row"><span class="loc">{esc(location)}</span>'
        f'<span>{esc(text)}</span></div>'
    )


def citation(citation: dict[str, Any]) -> str:
    source_type = str(citation.get("source_type", "")).upper()
    return (
        '<div class="cnc-citation">'
        f'<span class="src">{esc(source_type)}</span>'
        f'<span>{esc(citation.get("source_file", ""))} · {esc(citation.get("location", ""))} · '
        f'{esc(citation.get("field", ""))}</span></div>'
    )


def coverage_dots(excel: bool, pdf: bool, cad: bool) -> str:
    return "".join("●" if flag else "○" for flag in (excel, pdf, cad))


def empty(title: str, body: str) -> str:
    return (
        '<div class="cnc-card" style="border-left-color:#2A3138;min-height:0;text-align:left">'
        f'<div class="card-title" style="margin-bottom:6px">{esc(title)}</div>'
        f'<div class="card-line">{esc(body)}</div></div>'
    )


def foot(text: str) -> str:
    return f'<div class="cnc-foot">{esc(text)}</div>'
