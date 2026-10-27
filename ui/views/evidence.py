"""Evidence hierarchy: source-level citations, technical details, dataset map."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from src.dataset_manager import DatasetBundle, DatasetIndex
from .. import components as c
from .. import theme
from .dataset import Assets


def _audit_evidence(audit: Any) -> None:
    rows = []
    for finding in getattr(audit, "findings", ()):
        for item in finding.evidence:
            rows.append(
                {
                    "Check": finding.check,
                    "Source": item.source_type.upper(),
                    "File": item.source_file,
                    "Location": item.location,
                    "Field": item.field,
                    "Value": str(item.value),
                }
            )
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=260)
    else:
        st.caption("No source-level evidence was attached to these checks.")


def render(record: Any, drawing: Any, cad: Any, audit: Any, assets: Assets) -> None:
    st.markdown(c.section_label("Deterministic check results"), unsafe_allow_html=True)
    st.dataframe(
        pd.DataFrame(
            [
                {"Check": item.check, "Status": theme.status_label(item.status), "Finding": item.summary}
                for item in getattr(audit, "findings", ())
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    st.markdown(c.section_label("Evidence used by the deterministic checks"), unsafe_allow_html=True)
    _audit_evidence(audit)

    with st.expander(f"Manufacturing record — {len(record.evidence) if record else 0} cited cells", expanded=False):
        if record is None:
            st.markdown(c.empty("No workbook", "No Excel manufacturing record is associated with this part."), unsafe_allow_html=True)
        else:
            st.caption(f"Source: {record.source_file} · {record.sheet_name} · Excel row {record.excel_row}")
            st.dataframe(
                pd.DataFrame(
                    [
                        {"Field": item.field, "Value": str(item.value), "Evidence": f"{item.sheet_name}!{item.cell}"}
                        for item in record.evidence
                    ]
                ),
                width="stretch",
                hide_index=True,
            )

    with st.expander(
        f"Drawing evidence — {drawing.page_count if drawing else 0} page(s), "
        f"{len(drawing.evidence) if drawing else 0} text block(s)",
        expanded=False,
    ):
        if drawing is None:
            st.markdown(c.empty("No drawing", "No PDF drawing is associated with this part."), unsafe_allow_html=True)
        else:
            st.caption(
                f"Source: {drawing.source_file} · extraction: {drawing.extraction_method.replace('_', ' ')}"
            )
            for warning in drawing.warnings:
                st.markdown(c.callout("amber", "Extraction note", warning), unsafe_allow_html=True)
            if drawing.evidence:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Page": item.page,
                                "Text": item.text,
                                "Method": item.method,
                                "Confidence": f"{item.confidence:.0%}",
                            }
                            for item in drawing.evidence
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                    height=300,
                )
            if drawing.page_images:
                st.image(list(drawing.page_images)[:1], caption="Rendered page (vision fallback)", width="stretch")

    with st.expander(
        f"CAD evidence — {'measured' if cad is not None else 'no model'}"
        f"{', ' + str(cad.face_count) + ' faces' if cad is not None else ''}",
        expanded=False,
    ):
        if cad is None:
            st.markdown(
                c.empty("No CAD model", "No IGES model is associated with this part."),
                unsafe_allow_html=True,
            )
        else:
            metrics = {
                "Bounding box (mm)": " × ".join(f"{value:g}" for value in cad.bounding_box_mm),
                "Volume (mm³)": f"{cad.volume_mm3:,.2f}" if cad.volume_mm3 is not None else "not computed",
                "Surface area (mm²)": f"{cad.surface_area_mm2:,.2f}",
                "Solids / shells": f"{cad.solid_count} / {cad.shell_count}",
                "Faces / edges": f"{cad.face_count} / {cad.edge_count}",
                "Preview triangles": f"{cad.triangle_count:,}",
                "Topology valid": "yes" if cad.model_valid else "no",
                "Declared units": cad.units,
            }
            st.dataframe(
                pd.DataFrame([{"Measured field": key, "Value": value} for key, value in metrics.items()]),
                width="stretch",
                hide_index=True,
            )
            if cad.cylindrical_features:
                st.caption("Cylindrical candidates — verify hole versus external feature against the drawing.")
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Diameter (mm)": item.diameter_mm,
                                "Axial extent (mm)": item.length_mm,
                                "Axis": item.axis,
                                "Candidate count": item.candidate_count,
                                "Detection": item.detection_method,
                            }
                            for item in cad.cylindrical_features
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                )

    with st.expander("Dataset association", expanded=False):
        st.markdown(
            "".join(
                [
                    c.kv("Workbook", c.esc(Path(record.source_file).name) if record else "not associated"),
                    c.kv("Drawing", c.esc(Path(assets.pdf.name).name) if assets.pdf else "not associated"),
                    c.kv("CAD model", c.esc(Path(assets.cad.name).name) if assets.cad else "not associated"),
                    c.kv("PDF status", c.esc(assets.pdf_status)),
                    c.kv("IGES status", c.esc(assets.cad_status)),
                ]
            ),
            unsafe_allow_html=True,
        )
        st.caption("Association is deterministic and conservative. Ambiguous files require an explicit choice.")


def render_technical(record: Any, drawing: Any, cad: Any, audit: Any) -> None:
    st.caption("Raw structured output, shown only when requested.")
    st.markdown(c.section_label("Cross-source audit"), unsafe_allow_html=True)
    st.json(audit.to_dict(), expanded=False)
    for label, document in (("Manufacturing record", record), ("Drawing document", drawing), ("CAD document", cad)):
        if document is None:
            continue
        st.markdown(c.section_label(label), unsafe_allow_html=True)
        st.json(document.to_dict(), expanded=False)


def render_dataset_map(index: DatasetIndex, counts: Counter, bundle: DatasetBundle) -> None:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Part": item.part_number,
                    "Workbook rows": counts[item.part_number],
                    "PDF": item.pdf_status,
                    "PDF candidate(s)": ", ".join(file.name for file in item.pdf_candidates) or "—",
                    "IGES": item.cad_status,
                    "IGES candidate(s)": ", ".join(file.name for file in item.cad_candidates) or "—",
                }
                for item in index.matches
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    if index.unmatched_pdfs or index.unmatched_cads:
        st.markdown(
            c.callout(
                "amber",
                "Unassociated files",
                ", ".join((*index.unmatched_pdfs, *index.unmatched_cads)),
            ),
            unsafe_allow_html=True,
        )
    if bundle.ignored_files:
        st.caption("Ignored unsupported files: " + ", ".join(bundle.ignored_files[:10]))
