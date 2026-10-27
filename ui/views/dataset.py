"""Screen 2 — dataset validation, workbook mapping, and source association."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import streamlit as st

from src.dataset_manager import (
    DatasetBundle,
    DatasetFile,
    DatasetIndex,
    PartAssetMatch,
    discover_asset_part_numbers,
)
from src.excel_reader import (
    WorkbookReadError,
    discover_candidates,
    list_part_numbers,
    list_sheets,
    preview_sheet,
)
from .. import components as c
from .. import state

NOTICE_KEY = "association_notice"


@dataclass(frozen=True)
class WorkbookMapping:
    sheet: str | None = None
    header_row: int | None = None
    part_column: str | None = None
    parts: tuple[str, ...] = field(default_factory=tuple)

    @property
    def usable(self) -> bool:
        return self.sheet is not None and self.header_row is not None and self.part_column is not None


@dataclass(frozen=True)
class Assets:
    pdf: DatasetFile | None
    cad: DatasetFile | None
    pdf_status: str
    cad_status: str
    needs_action: bool = False


def resolve_workbook(bundle: DatasetBundle) -> WorkbookMapping:
    """Detect the workbook layout, then confirm it with the operator."""
    if bundle.workbook is None:
        st.info(
            "No Excel manufacturing record was supplied. The analysis will use the available PDF and IGES evidence only."
        )
        return WorkbookMapping()

    workbook_bytes = bundle.workbook.data
    try:
        candidates = discover_candidates(workbook_bytes)
        sheets = list_sheets(workbook_bytes)
    except WorkbookReadError as exc:
        st.error(str(exc))
        st.stop()

    if not sheets:
        st.error("The workbook does not contain a readable worksheet.")
        st.stop()

    detected = candidates[0] if candidates else None
    if detected is None:
        st.warning("A part-number column was not detected automatically. Confirm the mapping below.")

    with st.expander("Workbook mapping", expanded=detected is None):
        sheet_name = st.selectbox(
            "Worksheet",
            sheets,
            index=sheets.index(detected.sheet_name) if detected else 0,
            key="map_sheet",
        )
        header_row_number = int(
            st.number_input(
                "Header row number",
                min_value=1,
                max_value=50,
                value=detected.header_row + 1 if detected and sheet_name == detected.sheet_name else 1,
                step=1,
                key="map_header",
            )
        )
        try:
            preview = preview_sheet(workbook_bytes, sheet_name, header_row=header_row_number - 1, nrows=20)
        except WorkbookReadError as exc:
            st.error(str(exc))
            st.stop()
        columns = [str(column) for column in preview.columns]
        suggested = (
            detected.part_column
            if detected and detected.sheet_name == sheet_name and detected.header_row == header_row_number - 1
            else None
        )
        part_column = st.selectbox(
            "Part-number column",
            columns,
            index=columns.index(suggested) if suggested in columns else 0,
            key="map_column",
        )
        st.dataframe(
            preview.map(lambda value: "" if pd.isna(value) else str(value)),
            width="stretch",
            hide_index=True,
        )

    try:
        parts = list_part_numbers(
            workbook_bytes,
            sheet_name=sheet_name,
            header_row=header_row_number - 1,
            part_column=part_column,
        )
    except WorkbookReadError as exc:
        st.error(str(exc))
        st.stop()

    if not parts:
        st.warning(
            "No part numbers were found in the mapped workbook column; available PDF and IGES files can still be analyzed."
        )
    return WorkbookMapping(sheet_name, header_row_number - 1, part_column, tuple(parts))


def collect_parts(
    bundle: DatasetBundle, mapping: WorkbookMapping
) -> tuple[tuple[str, ...], bool]:
    """Workbook records first, then conservatively discovered asset identifiers."""
    parts = list(mapping.parts)
    known = set(parts)
    for part in discover_asset_part_numbers(bundle):
        if part not in known:
            parts.append(part)
            known.add(part)

    manual = False
    if not parts:
        manual_part = st.text_input(
            "Part number",
            help="No reliable identifier was found in the supplied filenames or PDF title blocks.",
            key="manual_part",
        ).strip()
        if not manual_part:
            st.info("Enter the component part number to analyze the supplied source file.")
            st.stop()
        parts.append(manual_part.upper().replace(" ", ""))
        manual = True
    return tuple(parts), manual


def _aggregate(matches: tuple[PartAssetMatch, ...], attribute: str) -> str:
    statuses = Counter(getattr(item, attribute) for item in matches)
    if statuses.get("ambiguous"):
        return "ambiguous"
    if statuses.get("matched"):
        return "matched"
    return "missing"


def _names(files: tuple[DatasetFile, ...], limit: int = 3) -> str:
    names = [Path(item.name).name for item in files[:limit]]
    suffix = f" +{len(files) - limit} more" if len(files) > limit else ""
    return c.esc(", ".join(names) + suffix) if names else '<span class="cnc-muted">none</span>'


def render_validation_strip(
    bundle: DatasetBundle,
    mapping: WorkbookMapping,
    index: DatasetIndex,
    counts: Counter,
    parts: tuple[str, ...],
    selected_part: str,
) -> tuple[Assets, bool]:
    """Show a compact source summary and only ask for input when matching is unclear."""
    duplicate_parts = [part for part in parts if counts[part] > 1]
    match = index.for_part(selected_part)
    assets = _resolve_assets(
        bundle,
        index,
        selected_part,
        match.pdf_status,
        match.cad_status,
    )

    labels = [
        f"Excel: {'ready' if counts[selected_part] == 1 else 'missing'}",
        f"PDF: {assets.pdf_status}",
        f"IGES: {assets.cad_status}",
    ]
    st.caption(" · ".join(labels))

    if st.session_state.get(NOTICE_KEY):
        st.caption(st.session_state.pop(NOTICE_KEY))

    if assets.needs_action or index.duplicate_parts:
        with st.expander("Choose matching files", expanded=True):
            _render_controls(bundle, index, selected_part, assets)
    elif index.unmatched_pdfs or index.unmatched_cads:
        with st.expander("Change file matching"):
            _render_controls(bundle, index, selected_part, assets)

    if bundle.ignored_files:
        st.caption("Ignored: " + ", ".join(bundle.ignored_files[:8]))

    return assets, bool(index.duplicate_parts)


def _resolve_assets(
    bundle: DatasetBundle,
    index: DatasetIndex,
    part: str,
    pdf_status: str,
    cad_status: str,
) -> Assets:
    """Resolve PDF/IGES for one part. Ambiguity is surfaced, never guessed."""
    match = index.for_part(part)
    pdf: DatasetFile | None = None
    cad: DatasetFile | None = None
    needs_action = False

    # Only genuine ambiguity blocks the operator. A source type that is simply
    # absent for this part is reported as missing, not as an action item.
    if len(match.pdf_candidates) == 1:
        pdf = match.pdf_candidates[0]
    elif len(match.pdf_candidates) > 1:
        needs_action = True

    if len(match.cad_candidates) == 1:
        cad = match.cad_candidates[0]
    elif len(match.cad_candidates) > 1:
        needs_action = True

    return Assets(pdf, cad, match.pdf_status, match.cad_status, needs_action)


def _render_controls(
    bundle: DatasetBundle, index: DatasetIndex, part: str, assets: Assets
) -> None:
    """Picker widgets. Their return values are authoritative on the next run."""
    match = index.for_part(part)
    st.caption(
        f"Selected part **{part}** · PDF {assets.pdf_status} · IGES {assets.cad_status}. "
        "Automatic association only accepts a single unambiguous file."
    )

    if len(match.pdf_candidates) > 1:
        st.selectbox(
            "Multiple drawings match this part — choose the correct one",
            [item.name for item in match.pdf_candidates],
            index=None,
            placeholder="Select the correct drawing…",
            key=f"pdf_pick_{part}",
        )
    elif not match.pdf_candidates and bundle.pdfs:
        st.selectbox(
            "No drawing matched this part — optionally associate one",
            ["Not provided / do not associate", *[item.name for item in bundle.pdfs]],
            key=f"pdf_pick_{part}",
        )

    if len(match.cad_candidates) > 1:
        st.selectbox(
            "Multiple IGES models match this part — choose the correct one",
            [item.name for item in match.cad_candidates],
            index=None,
            placeholder="Select the correct model…",
            key=f"cad_pick_{part}",
        )
    elif not match.cad_candidates and bundle.cads:
        st.selectbox(
            "No IGES model matched this part — optionally associate one",
            ["Not provided / do not associate", *[item.name for item in bundle.cads]],
            key=f"cad_pick_{part}",
        )

    if not bundle.pdfs and not bundle.cads:
        st.caption("Only the workbook is present; nothing to associate.")


def apply_controls(
    bundle: DatasetBundle, index: DatasetIndex, part: str, assets: Assets
) -> Assets:
    """Read the operator's picker choices and finalize the association."""
    match = index.for_part(part)
    pdf, cad = assets.pdf, assets.cad
    pdf_status, cad_status = assets.pdf_status, assets.cad_status

    pdf_pick = st.session_state.get(f"pdf_pick_{part}")
    if pdf_pick and pdf_pick != "Not provided / do not associate":
        found = next((item for item in bundle.pdfs if item.name == pdf_pick), None)
        if found is not None:
            pdf = found
            pdf_status = "matched" if found in match.pdf_candidates else "selected"
    elif pdf_pick == "Not provided / do not associate":
        pdf = None
        pdf_status = "missing"

    cad_pick = st.session_state.get(f"cad_pick_{part}")
    if cad_pick and cad_pick != "Not provided / do not associate":
        found = next((item for item in bundle.cads if item.name == cad_pick), None)
        if found is not None:
            cad = found
            cad_status = "matched" if found in match.cad_candidates else "selected"
    elif cad_pick == "Not provided / do not associate":
        cad = None
        cad_status = "missing"

    needs_action = (len(match.pdf_candidates) > 1 and not pdf_pick) or (
        len(match.cad_candidates) > 1 and not cad_pick
    )
    return Assets(pdf, cad, pdf_status, cad_status, needs_action)
