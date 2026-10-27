"""AI question area — evidence-bound answers about the selected part."""

from __future__ import annotations

from typing import Any

import streamlit as st

from src.llm_client import LLMConfigurationError, LLMResponseError, answer_question
from src.pdf_reader import retrieve_drawing_evidence
from .. import components as c
from .. import state

PRESETS: tuple[str, ...] = (
    "What are the dimensions?",
    "Do the files disagree?",
    "What information is missing?",
)

CONFIDENCE_TONES = {"high": "green", "medium": "steel", "low": "amber", "not_available": "muted"}


def _sources(record: Any, drawing: Any, cad: Any) -> list[str]:
    return [
        name
        for name, present in (
            ("Manufacturing record", record is not None),
            ("Drawing", drawing is not None),
            ("CAD model", cad is not None),
        )
        if present
    ]


def _render_assistant(message: dict[str, Any]) -> None:
    if message.get("error"):
        st.markdown(
            c.callout("red", "Answer unavailable", message["error"]), unsafe_allow_html=True
        )
        return

    st.markdown(message.get("answer", ""))
    tone = CONFIDENCE_TONES.get(message.get("confidence", "low"), "muted")
    sources = ", ".join(message.get("sources", [])) or "no sources"
    st.markdown(
        f'<div style="display:flex;gap:10px;align-items:center;margin-top:6px;flex-wrap:wrap">'
        f'{c.pill_text("Confidence: " + str(message.get("confidence", "low")).replace("_", " "), tone, small=True)}'
        f'<span class="cnc-mono" style="font-size:10px;color:#8794A1;letter-spacing:.06em">'
        f"SOURCES: {c.esc(sources.upper())}</span></div>",
        unsafe_allow_html=True,
    )

    evidence = message.get("evidence") or []
    if evidence:
        st.markdown(
            '<div class="cnc-section-label" style="margin-top:10px">Validated citations</div>'
            + "".join(c.citation(item) for item in evidence),
            unsafe_allow_html=True,
        )
    else:
        st.caption("No citation could be validated for this answer — treat it as unverified.")

    for warning in message.get("warnings") or []:
        st.markdown(c.callout("amber", "Warning", warning), unsafe_allow_html=True)

    retrieved = message.get("retrieved") or 0
    if retrieved:
        st.caption(f"{retrieved} drawing text block(s) were retrieved and supplied as retrieval evidence.")


def render_chat(
    part: str,
    record: Any,
    drawing: Any,
    cad: Any,
    audit: Any,
    api_configured: bool,
) -> None:
    # st.chat_input placed directly in the page body makes Streamlit scroll the
    # main container to the bottom on load, which hides the part workspace.
    # Inside a container it stays visible without stealing the initial scroll.
    with st.container():
        _render_chat_body(part, record, drawing, cad, audit, api_configured)


def _render_chat_body(
    part: str,
    record: Any,
    drawing: Any,
    cad: Any,
    audit: Any,
    api_configured: bool,
) -> None:
    history = state.chat_history(part)
    for message in history:
        with st.chat_message(message["role"]):
            if message["role"] == "user":
                st.markdown(message["content"])
            else:
                _render_assistant(message)

    if not api_configured:
        st.markdown(
            c.callout(
                "amber",
                "DeepSeek unavailable",
                "Add DEEPSEEK_API_KEY to enable questions. The engineering checks still work.",
            ),
            unsafe_allow_html=True,
        )

    columns = st.columns(3, gap="small")
    clicked: str | None = None
    for index, preset in enumerate(PRESETS):
        if columns[index].button(preset, key=f"preset_{part}_{index}", width="stretch", disabled=not api_configured):
            clicked = preset

    submitted = st.chat_input(f"Ask about part {part}", key=f"chat_input_{part}")

    question = (submitted or clicked or "").strip()
    if not question:
        return

    state.append_chat(part, {"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    if not api_configured:
        message = {
            "role": "assistant",
            "error": "Configure DEEPSEEK_API_KEY to enable evidence-bound answers.",
        }
        state.append_chat(part, message)
        with st.chat_message("assistant"):
            _render_assistant(message)
        return

    retrieved = retrieve_drawing_evidence(drawing, question) if drawing is not None else ()
    with st.spinner("Checking the evidence…"):
        try:
            result = answer_question(
                record,
                question,
                part_number=part,
                drawing=drawing,
                drawing_evidence=retrieved,
                cad=cad,
                audit=audit,
            )
        except (LLMConfigurationError, LLMResponseError) as exc:
            message = {"role": "assistant", "error": str(exc)}
        except Exception as exc:  # defensive: never leave the chat half-written
            message = {"role": "assistant", "error": f"Unexpected error: {exc}"}
        else:
            message = {
                "role": "assistant",
                "answer": result["answer"],
                "confidence": result["confidence"],
                "evidence": result["evidence"],
                "warnings": result["warnings"],
                "sources": _sources(record, drawing, cad),
                "retrieved": len(retrieved),
            }
    state.append_chat(part, message)
    with st.chat_message("assistant"):
        _render_assistant(message)
