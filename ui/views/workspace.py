"""Screen 3 — the part workspace: navigation, model viewer, inspection result."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dataset_manager import DatasetBundle, DatasetIndex
from src.excel_reader import normalize_label
from .. import caching
from .. import components as c
from .. import theme
from . import assistant, evidence
from .dataset import Assets

CAMERAS: dict[str, dict[str, float]] = {
    "Isometric": {"x": 1.25, "y": 1.20, "z": 0.95},
    "Front": {"x": 0.0, "y": -1.55, "z": 0.0},
    "Top": {"x": 0.0, "y": 0.0, "z": 1.55},
    "Right": {"x": 1.55, "y": 0.0, "z": 0.0},
    "Reset": {"x": 1.25, "y": 1.20, "z": 0.95},
}
VIEW_BUTTONS = ("Isometric", "Front", "Top", "Right", "Reset")

_AXIS = {
    "backgroundcolor": "rgba(0,0,0,0)",
    "gridcolor": "#262D34",
    "zerolinecolor": "#39424B",
    "color": "#8794A1",
    "tickfont": {"size": 9, "family": "JetBrains Mono, Consolas, monospace"},
    "title_font": {"size": 10, "color": "#8794A1"},
}


@dataclass
class WorkspaceContext:
    part: str
    parts: tuple[str, ...]
    counts: Counter
    index: DatasetIndex
    bundle: DatasetBundle
    assets: Assets
    record: Any
    drawing: Any
    cad: Any
    audit: Any
    results: dict[str, Any]
    api_configured: bool


def _sources_verified(audit: Any) -> int:
    return max(0, 3 - len(getattr(audit, "missing_sources", ()) or ()))


def _field_value(record: Any, fragment: str) -> Any:
    if record is None:
        return None
    wanted = normalize_label(fragment)
    for item in record.evidence:
        if wanted in normalize_label(item.field):
            return item.value
    return None


def _finding(audit: Any, check: str) -> Any:
    for item in getattr(audit, "findings", ()):
        if item.check == check:
            return item
    return None


def _dimensions(cad: Any) -> str:
    if cad is None:
        return "—"
    return " × ".join(f"{value:g}" for value in cad.bounding_box_mm) + " mm"


def _units(cad: Any) -> str:
    """IGES declares a long explanatory string; the panel needs the unit only."""
    if cad is None:
        return "—"
    first = str(cad.units).strip().split(" ")[0]
    return first or "mm"


def _warning_lead(text: str) -> str:
    lowered = text.lower()
    if "scale" in lowered or "unit" in lowered:
        return "Scale warning"
    if "cylind" in lowered or "hole" in lowered or "boss" in lowered:
        return "Geometry note"
    return "Model note"


def _viewer(ctx: WorkspaceContext) -> None:
    if ctx.cad is not None:
        _cad_viewer(ctx.cad)
        return
    if ctx.drawing is not None and ctx.assets.pdf is not None:
        _drawing_preview(ctx.assets.pdf)
        return
    _record_fallback(ctx.record)


def _cad_viewer(cad: Any) -> None:
    picked = st.columns([1, 1, 1, 1, 1], gap="small")
    for column, name in zip(picked, VIEW_BUTTONS, strict=True):
        if column.button(name, key=f"view_{name}", width="stretch"):
            st.session_state.camera_view = name
            st.rerun()

    step = max(1, len(cad.triangles) // 50_000)
    triangles = cad.triangles[::step]
    vertices = cad.vertices

    # Explicit ranges plus a manual aspect ratio keep the whole model inside the
    # frame; auto-fitting cropped thin plates at the axis edges.
    xs = [point[0] for point in vertices]
    ys = [point[1] for point in vertices]
    zs = [point[2] for point in vertices]

    def span(values: list[float]) -> tuple[float, float, float]:
        lo, hi = min(values), max(values)
        width = max(hi - lo, 1e-6)
        return lo, hi, width

    span_x, span_y, span_z = span(xs), span(ys), span(zs)
    largest = max(span_x[2], span_y[2], span_z[2])

    def axis(values: tuple[float, float, float], title: str) -> dict[str, Any]:
        lo, hi, width = values
        pad = width * 0.08
        return {**_AXIS, "title": title, "range": [lo - pad, hi + pad]}

    figure = go.Figure(
        data=[
            go.Mesh3d(
                x=xs,
                y=ys,
                z=zs,
                i=[item[0] for item in triangles],
                j=[item[1] for item in triangles],
                k=[item[2] for item in triangles],
                color="#5AA3D6",
                flatshading=True,
                lighting={"ambient": 0.45, "diffuse": 0.82, "specular": 0.22},
                hoverinfo="skip",
                name=cad.source_file,
            )
        ]
    )
    camera = st.session_state.get("camera_view", "Isometric")
    figure.update_layout(
        height=500,
        margin={"l": 0, "r": 0, "t": 8, "b": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        scene={
            "aspectmode": "manual",
            "aspectratio": {
                "x": span_x[2] / largest,
                "y": span_y[2] / largest,
                "z": max(span_z[2] / largest, 0.04),
            },
            "bgcolor": "rgba(0,0,0,0)",
            "camera": {"eye": CAMERAS.get(camera, CAMERAS["Isometric"]), "up": {"x": 0, "y": 0, "z": 1}},
            "xaxis": axis(span_x, "X (mm)"),
            "yaxis": axis(span_y, "Y (mm)"),
            "zaxis": axis(span_z, "Z (mm)"),
        },
        showlegend=False,
    )
    st.plotly_chart(
        figure,
        width="stretch",
        config={"displaylogo": False, "scrollZoom": True, "modeBarButtonsToRemove": ["sendDataToCloud"]},
    )
    st.caption(
        f"{Path(cad.source_file).name} · {camera.lower()} view · "
        f"OpenCascade measurement · drag to orbit, scroll to zoom"
    )


def _drawing_preview(pdf_asset: Any) -> None:
    pages = caching.drawing_pages(pdf_asset.data, 1)
    if pages:
        st.image(pages[0], caption=f"{Path(pdf_asset.name).name} · page 1", width="stretch")
    else:
        st.info("The drawing could not be rendered as an image; its extracted text is shown under Evidence.")


def _record_fallback(record: Any) -> None:
    if record is None:
        st.markdown(
            c.empty("No visual source", "Neither a drawing nor an IGES model is associated with this part."),
            unsafe_allow_html=True,
        )
        return
    st.markdown(c.section_label("Manufacturing record only"), unsafe_allow_html=True)
    st.dataframe(
        pd.DataFrame(
            [{"Field": item.field, "Value": str(item.value), "Cell": f"{item.sheet_name}!{item.cell}"} for item in record.evidence]
        ),
        width="stretch",
        hide_index=True,
        height=340,
    )


def _result_panel(ctx: WorkspaceContext) -> None:
    audit = ctx.audit
    if audit.status == "conflict":
        st.error("The supplied files disagree.")
    elif audit.status == "incomplete":
        st.warning("Some source files are missing. Available evidence was still analyzed.")
    elif audit.status == "review":
        st.warning("One or more checks need review.")
    else:
        st.success("No disagreement was found.")

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Check": item.check,
                    "Result": theme.status_label(item.status),
                    "Details": item.summary,
                }
                for item in audit.findings
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    if ctx.cad is not None:
        for warning in ctx.cad.warnings:
            st.warning(warning)


def _part_selector(ctx: WorkspaceContext) -> None:
    search = st.text_input(
        "Filter parts",
        key="part_search",
        placeholder="Filter part number…",
        label_visibility="collapsed",
    ).strip().upper()
    visible = [part for part in ctx.parts if not search or search in part]
    if not visible:
        st.caption("No part matches that filter.")
        visible = list(ctx.parts)

    if st.session_state.get("part_selector") not in visible:
        st.session_state.part_selector = visible[0]

    def label(part: str) -> str:
        match = ctx.index.for_part(part)
        dots = c.coverage_dots(ctx.counts[part] == 1, match.pdf_status == "matched", match.cad_status == "matched")
        entry = (ctx.results or {}).get(part)
        status = entry["audit"].status.upper() if entry else ""
        duplicate = " DUPLICATE" if ctx.counts[part] > 1 else ""
        gap = "\u00a0\u00a0\u00a0"
        return f"{part}{gap}{dots}{gap}{status}{duplicate}".rstrip()

    # The stylesheet targets .st-key-part_selector, which Streamlit derives from this key.
    st.radio("Part", visible, key="part_selector", format_func=label, label_visibility="collapsed")

    statuses = Counter(entry["audit"].status for entry in (ctx.results or {}).values() if entry)
    st.markdown(
        f'<div class="cnc-mono cnc-dim" style="margin-top:8px;font-size:10px;line-height:1.7">'
        f"{len(ctx.parts)} parts · {statuses.get('consistent', 0)} consistent · "
        f"{statuses.get('conflict', 0)} conflict · {statuses.get('incomplete', 0)} incomplete · "
        f"{statuses.get('review', 0)} review<br>● source matched · ○ source absent</div>",
        unsafe_allow_html=True,
    )


def render(ctx: WorkspaceContext) -> None:
    verified = _sources_verified(ctx.audit)
    st.subheader(f"Part {ctx.part}")
    metric_a, metric_b, metric_c, metric_d = st.columns(4)
    metric_a.metric("Status", theme.status_label(ctx.audit.status))
    metric_b.metric("Sources", f"{verified}/3")
    metric_c.metric("Conflicts", ctx.audit.conflict_count)
    metric_d.metric("Dimensions", _dimensions(ctx.cad))

    overview_tab, evidence_tab, ask_tab = st.tabs(["Overview", "Evidence", "Ask DeepSeek"])
    with overview_tab:
        visual, result = st.columns([1.35, 1], gap="medium")
        with visual:
            _viewer(ctx)
        with result:
            _result_panel(ctx)

    with evidence_tab:
        evidence.render(ctx.record, ctx.drawing, ctx.cad, ctx.audit, ctx.assets)
        with st.expander("Technical details"):
            evidence.render_technical(ctx.record, ctx.drawing, ctx.cad, ctx.audit)
        with st.expander("Dataset map"):
            evidence.render_dataset_map(ctx.index, ctx.counts, ctx.bundle)

    with ask_tab:
        assistant.render_chat(
            ctx.part,
            ctx.record,
            ctx.drawing,
            ctx.cad,
            ctx.audit,
            ctx.api_configured,
        )
