"""Simple start screen: use the demo or upload engineering files."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

DEMO_BUNDLE = Path("outputs/stretch_dataset/cnc_stretch_dataset.zip")


def _load_demo() -> None:
    st.session_state.dataset_files = [(DEMO_BUNDLE.name, DEMO_BUNDLE.read_bytes())]
    st.session_state.demo_loaded = True
    st.query_params["dataset"] = "demo"
    st.rerun()


def render(*, api_configured: bool, error: str | None = None) -> None:
    st.title("CNC Part Analyzer")
    st.write("Upload the available Excel, PDF, and IGES files. Missing file types are allowed.")

    if error:
        st.error(error)

    left, right = st.columns(2, gap="medium")
    with left:
        if st.button(
            "Run demo",
            type="primary",
            width="stretch",
            disabled=not DEMO_BUNDLE.is_file(),
        ):
            _load_demo()
    with right:
        st.caption("DeepSeek ready" if api_configured else "DeepSeek key not configured")

    uploads = st.file_uploader(
        "Upload files",
        type=["zip", "xlsx", "xlsm", "xls", "pdf", "igs", "iges"],
        accept_multiple_files=True,
        help="Upload one ZIP or select the available source files together.",
    )
    st.caption("Accepted: ZIP, Excel, PDF, IGS and IGES")

    if uploads:
        st.session_state.dataset_files = [(item.name, item.getvalue()) for item in uploads]
        st.session_state.demo_loaded = False
        if st.query_params.get("dataset"):
            del st.query_params["dataset"]
        st.rerun()

