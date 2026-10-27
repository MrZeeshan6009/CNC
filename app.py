"""CNC Intelligence Workbench — application orchestration.

Analysis logic lives in ``src/``. This module owns the screen stages only:
ingest -> validate -> measure -> workspace.
"""

from __future__ import annotations

import os
from collections import Counter
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from src.cad_reader import CADReadError
from src.cross_check import build_cross_source_audit
from src.dataset_manager import DatasetBundle, DatasetIndex, DatasetReadError, build_dataset_index, ingest_dataset
from src.excel_reader import DuplicatePartError, PartNotFoundError, WorkbookReadError, find_part
from src.pdf_reader import PDFReadError
from ui import caching
from ui import components as c
from ui import state as ui_state
from ui import theme
from ui.views import dataset as dataset_view
from ui.views import start as start_view
from ui.views import workspace
from ui.views.dataset import Assets, WorkbookMapping
from ui.views.workspace import WorkspaceContext

APP_TITLE = "CNC Part Analyzer"

# Part-level failures that must be reported, never swallowed.
ANALYSIS_ERRORS = (
    PartNotFoundError,
    DuplicatePartError,
    WorkbookReadError,
    PDFReadError,
    CADReadError,
    ValueError,
)

# Pre-measuring every part makes part switching instant for normal datasets.
PREWARM_LIMIT = 8


def _load_secrets() -> None:
    load_dotenv()
    try:
        for secret_name in ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL"):
            if secret_name in st.secrets and not os.getenv(secret_name):
                os.environ[secret_name] = str(st.secrets[secret_name])
    except FileNotFoundError:
        pass
    except Exception:
        # A malformed secrets file must not take the whole app down.
        pass


def api_configured() -> bool:
    return bool(os.getenv("DEEPSEEK_API_KEY"))


def _signature(part: str, assets: Assets, mapping: WorkbookMapping) -> tuple:
    return ui_state.analysis_signature(
        part,
        assets.pdf.name if assets.pdf else None,
        assets.cad.name if assets.cad else None,
        mapping.sheet,
        mapping.header_row,
        mapping.part_column,
    )


def _auto_assets(bundle: DatasetBundle, index: DatasetIndex, part: str) -> Assets:
    """Association without UI: only a single unambiguous candidate is accepted."""
    match = index.for_part(part)
    pdf = match.pdf_candidates[0] if len(match.pdf_candidates) == 1 else None
    cad = match.cad_candidates[0] if len(match.cad_candidates) == 1 else None
    return Assets(pdf, cad, match.pdf_status, match.cad_status, False)


def _measure(
    part: str, bundle: DatasetBundle, mapping: WorkbookMapping, counts: Counter, assets: Assets
) -> dict[str, Any]:
    record = None
    if counts.get(part) == 1:
        if bundle.workbook is None or not mapping.usable:
            raise WorkbookReadError("The selected Excel record could not be mapped.")
        record = find_part(
            bundle.workbook.data,
            source_file=bundle.workbook.name,
            part_number=part,
            sheet_name=mapping.sheet,
            header_row=mapping.header_row,
            part_column=mapping.part_column,
        )
    drawing = caching.drawing_document(assets.pdf.data, assets.pdf.name) if assets.pdf else None
    cad = caching.cad_document(assets.cad.data, assets.cad.name) if assets.cad else None
    audit = build_cross_source_audit(record, drawing=drawing, cad=cad, part_number=part)
    return {"record": record, "drawing": drawing, "cad": cad, "audit": audit}


def _prewarm(
    bundle: DatasetBundle,
    mapping: WorkbookMapping,
    index: DatasetIndex,
    counts: Counter,
    parts: tuple[str, ...],
) -> None:
    if st.session_state.get("prewarmed") == st.session_state.get("dataset_signature"):
        return
    st.session_state.prewarmed = st.session_state.get("dataset_signature")
    if len(parts) > PREWARM_LIMIT:
        return

    with st.spinner(f"Indexing sources and measuring geometry for {len(parts)} part(s)…"):
        for part in parts:
            if counts.get(part, 0) > 1:
                continue  # ambiguous workbook rows are reported on selection
            assets = _auto_assets(bundle, index, part)
            signature = _signature(part, assets, mapping)
            if ui_state.cache_get(part, signature):
                continue
            try:
                measured = _measure(part, bundle, mapping, counts, assets)
            except ANALYSIS_ERRORS:
                continue
            ui_state.cache_put(part, signature, **measured)


def _run_workspace(
    bundle: DatasetBundle,
    mapping: WorkbookMapping,
    index: DatasetIndex,
    counts: Counter,
    parts: tuple[str, ...],
    assets: Assets,
    selected_part: str,
) -> None:
    signature = _signature(selected_part, assets, mapping)
    entry = ui_state.cache_get(selected_part, signature)
    if entry is None:
        try:
            with st.spinner("Measuring IGES geometry and rendering standard views…"):
                measured = _measure(selected_part, bundle, mapping, counts, assets)
        except ANALYSIS_ERRORS as exc:
            st.error(str(exc))
            st.stop()
        entry = ui_state.cache_put(selected_part, signature, **measured)

    ui_state.activate(selected_part, entry)

    workspace.render(
        WorkspaceContext(
            part=selected_part,
            parts=parts,
            counts=counts,
            index=index,
            bundle=bundle,
            assets=assets,
            record=entry["record"],
            drawing=entry["drawing"],
            cad=entry["cad"],
            audit=entry["audit"],
            results=dict(st.session_state.get("part_results") or {}),
            api_configured=api_configured(),
        )
    )


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="⚙", layout="wide", initial_sidebar_state="collapsed")
    _load_secrets()
    theme.inject()
    ui_state.init_state()

    named_files = st.session_state.get("dataset_files")
    if not named_files and st.query_params.get("dataset") == "demo" and start_view.DEMO_BUNDLE.is_file():
        # Restores the demonstration dataset after a browser refresh, when the
        # session state has been lost but the URL parameter survives.
        st.session_state.dataset_files = [
            (start_view.DEMO_BUNDLE.name, start_view.DEMO_BUNDLE.read_bytes())
        ]
        st.session_state.demo_loaded = True
        named_files = st.session_state.dataset_files
    if not named_files:
        start_view.render(api_configured=api_configured())
        return

    try:
        bundle = ingest_dataset(named_files)
    except DatasetReadError as exc:
        st.session_state.dataset_files = None
        start_view.render(api_configured=api_configured(), error=str(exc))
        return

    ui_state.sync_dataset(ui_state.dataset_signature(named_files))

    bar, action = st.columns([8, 2], gap="small")
    with bar:
        st.markdown(
            c.topbar(
                api_configured=api_configured(),
                meta=f"{bundle.file_count} files",
            ),
            unsafe_allow_html=True,
        )
    with action:
        if st.button("Start over", width="stretch", key="reset_dataset"):
            ui_state.reset_dataset()
            st.rerun()

    mapping = dataset_view.resolve_workbook(bundle)
    parts, manual = dataset_view.collect_parts(bundle, mapping)
    index = build_dataset_index(bundle, parts, allow_single_file_fallback=manual)
    counts = Counter(mapping.parts)

    if st.session_state.get("part_selector") not in parts:
        st.session_state.part_selector = parts[0]
    st.selectbox("Part number", parts, key="part_selector")
    selected_part = st.session_state.part_selector

    assets, _ = dataset_view.render_validation_strip(bundle, mapping, index, counts, parts, selected_part)
    assets = dataset_view.apply_controls(bundle, index, selected_part, assets)

    if counts.get(selected_part, 0) > 1:
        st.error(
            "This part appears more than once in the workbook. Resolve the duplicate rows before analysis."
        )
        st.stop()

    _prewarm(bundle, mapping, index, counts, parts)
    _run_workspace(bundle, mapping, index, counts, parts, assets, selected_part)



main()
