from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from src.pdf_reader import PDFReadError, extract_drawing, retrieve_drawing_evidence


def _text_pdf() -> bytes:
    output = io.BytesIO()
    drawing = canvas.Canvas(output, pagesize=(612, 792))
    drawing.setFont("Helvetica-Bold", 14)
    drawing.drawString(50, 740, "ENGINEERING DRAWING - PART 2280")
    drawing.setFont("Helvetica", 11)
    drawing.drawString(50, 700, "MATERIAL: ALUMINUM 6061-T6")
    drawing.drawString(50, 680, "SURFACE FINISH: Ra 1.6")
    drawing.drawString(50, 660, "GENERAL TOLERANCE: +/- 0.10 mm")
    drawing.showPage()
    drawing.save()
    return output.getvalue()


def _image_only_pdf() -> bytes:
    image = Image.new("RGB", (800, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.text((30, 30), "SCANNED DRAWING PART 2280", fill="black")
    output = io.BytesIO()
    drawing = canvas.Canvas(output, pagesize=(612, 792))
    drawing.drawImage(ImageReader(image), 40, 400, width=520, height=260)
    drawing.showPage()
    drawing.save()
    return output.getvalue()


def test_extracts_page_aware_drawing_text() -> None:
    document = extract_drawing(_text_pdf(), "2280_drawing.pdf")
    assert document.page_count == 1
    assert document.has_searchable_text
    assert document.extraction_method == "embedded_text"
    assert any("ALUMINUM 6061-T6" in item.text for item in document.evidence)
    assert all(item.page == 1 for item in document.evidence)


def test_retrieval_prefers_relevant_drawing_block() -> None:
    document = extract_drawing(_text_pdf(), "2280_drawing.pdf")
    evidence = retrieve_drawing_evidence(document, "What surface finish is required?", limit=2)
    assert evidence
    assert "SURFACE FINISH" in evidence[0].text


def test_image_only_pdf_uses_vision_fallback() -> None:
    document = extract_drawing(_image_only_pdf(), "scan.pdf")
    assert document.extraction_method == "vision_fallback"
    assert document.page_images
    assert document.warnings


def test_invalid_pdf_is_rejected() -> None:
    with pytest.raises(PDFReadError):
        extract_drawing(b"not a pdf", "broken.pdf")

