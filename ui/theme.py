"""Palette, status vocabulary, and stylesheet injection."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
STYLESHEET = ROOT / "assets" / "styles.css"

COLORS = {
    "steel": "#4D9FD6",
    "amber": "#E0A03C",
    "red": "#D9553F",
    "green": "#46A87A",
    "muted": "#8794A1",
    "text": "#DCE3EA",
}

# Plain-language vocabulary. Judges should never decode internal enum names.
STATUS_LABELS = {
    "consistent": "Consistent",
    "conflict": "Conflict",
    "incomplete": "Incomplete",
    "review": "Review",
    "pass": "Pass",
    "warning": "Review",
    "missing": "Missing",
    "matched": "Matched",
    "ambiguous": "Ambiguous",
    "unmatched": "Unmapped",
}

STATUS_TONES = {
    "consistent": "green",
    "pass": "green",
    "matched": "green",
    "conflict": "red",
    "incomplete": "amber",
    "review": "amber",
    "warning": "amber",
    "missing": "amber",
    "ambiguous": "amber",
    "unmatched": "muted",
}


def tone_color(tone: str) -> str:
    return COLORS.get(tone, COLORS["muted"])


def status_tone(status: str) -> str:
    return STATUS_TONES.get(status, "muted")


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status.replace("_", " ").title())


def status_color(status: str) -> str:
    return tone_color(status_tone(status))


def inject() -> None:
    """Apply the workstation theme. Falls back silently if assets are missing."""
    try:
        css = STYLESHEET.read_text(encoding="utf-8")
    except OSError:
        return
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
