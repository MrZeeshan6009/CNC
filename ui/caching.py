"""Cached, side-effect-free extraction helpers shared by the views."""

from __future__ import annotations

import streamlit as st

from src.cad_reader import extract_cad
from src.pdf_reader import extract_drawing, render_page_images


@st.cache_data(show_spinner=False)
def drawing_document(data: bytes, name: str):
    return extract_drawing(data, name)


@st.cache_data(show_spinner=False)
def cad_document(data: bytes, name: str):
    return extract_cad(data, name)


@st.cache_data(show_spinner=False)
def drawing_pages(data: bytes, limit: int = 1):
    """Render pages for display only. Independent of the OCR/vision fallback."""
    return render_page_images(data, max_pages=limit)
