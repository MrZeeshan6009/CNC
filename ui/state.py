"""Session state, dataset/analysis signatures, and analysis caching.

Existing state keys are preserved so behaviour does not change:
``dataset_signature``, ``analysis_signature``, ``analysis_ready``,
``part_record``, ``drawing_document``, ``cad_document``, ``audit_report``.
"""

from __future__ import annotations

import hashlib
from typing import Any

import streamlit as st

ANALYSIS_KEYS = (
    "part_record",
    "drawing_document",
    "cad_document",
    "audit_report",
    "analysis_signature",
    "analysis_ready",
)

DEFAULTS: dict[str, Any] = {
    "stage": "start",
    "demo_loaded": False,
    "dataset_files": None,
    "dataset_signature": None,
    "analysis_signature": None,
    "analysis_ready": False,
    "part_record": None,
    "drawing_document": None,
    "cad_document": None,
    "audit_report": None,
    "part_results": {},
    "prewarmed": None,
    "selected_part": None,
    "assoc": {},
    "chat": {},
    "pending_question": None,
    "camera_view": "Isometric",
    "lower_view": "Evidence",
    "part_search": "",
}


def init_state() -> None:
    for key, value in DEFAULTS.items():
        st.session_state.setdefault(key, value if not isinstance(value, (dict, list)) else type(value)())


def dataset_signature(named_files: list[tuple[str, bytes]]) -> str:
    """Unchanged hashing scheme: order-sensitive name + content digest."""
    return hashlib.sha256(
        b"".join(name.encode("utf-8") + hashlib.sha256(data).digest() for name, data in named_files)
    ).hexdigest()


def sync_dataset(signature: str) -> bool:
    """Invalidate per-dataset caches when the uploaded files change."""
    if st.session_state.get("dataset_signature") == signature:
        return False
    for key in ANALYSIS_KEYS:
        st.session_state.pop(key, None)
    st.session_state.dataset_signature = signature
    st.session_state.part_results = {}
    st.session_state.prewarmed = None
    st.session_state.assoc = {}
    st.session_state.chat = {}
    st.session_state.selected_part = None
    st.session_state.analysis_ready = False
    return True


def analysis_signature(
    part: str,
    pdf_name: str | None,
    cad_name: str | None,
    sheet: str | None,
    header_row: int | None,
    part_column: str | None,
) -> tuple:
    return (part, pdf_name, cad_name, sheet, header_row, part_column)


def cache_get(part: str, signature: tuple) -> dict[str, Any] | None:
    entry = st.session_state.get("part_results", {}).get(part)
    if entry and entry.get("signature") == signature:
        return entry
    return None


def cache_put(part: str, signature: tuple, record: Any, drawing: Any, cad: Any, audit: Any) -> dict[str, Any]:
    entry = {
        "signature": signature,
        "record": record,
        "drawing": drawing,
        "cad": cad,
        "audit": audit,
    }
    results = dict(st.session_state.get("part_results") or {})
    results[part] = entry
    st.session_state.part_results = results
    return entry


def activate(part: str, entry: dict[str, Any]) -> None:
    """Publish the active part into the established session keys."""
    st.session_state.part_record = entry["record"]
    st.session_state.drawing_document = entry["drawing"]
    st.session_state.cad_document = entry["cad"]
    st.session_state.audit_report = entry["audit"]
    st.session_state.analysis_signature = entry["signature"]
    st.session_state.analysis_ready = True


def chat_history(part: str) -> list[dict[str, Any]]:
    return st.session_state.setdefault("chat", {}).setdefault(part, [])


def append_chat(part: str, message: dict[str, Any]) -> None:
    history = st.session_state.setdefault("chat", {}).setdefault(part, [])
    history.append(message)


def reset_analysis_only() -> None:
    for key in ANALYSIS_KEYS:
        st.session_state.pop(key, None)
    st.session_state.part_results = {}
    st.session_state.prewarmed = None


def reset_dataset() -> None:
    init_state()
    for key in list(DEFAULTS):
        st.session_state.pop(key, None)
    init_state()
    for key in ("dataset", "demo"):
        if st.query_params.get(key):
            del st.query_params[key]
