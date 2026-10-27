from __future__ import annotations

import re
import shutil
from collections import Counter

import pymupdf

from .models import DrawingDocument, DrawingEvidence


MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_PAGES = 30
MAX_VISION_PAGES = 3

STOPWORDS = {
    "a", "about", "an", "and", "are", "does", "for", "from", "how", "in", "is",
    "it", "of", "on", "part", "the", "this", "to", "what", "which", "with",
}

QUERY_EXPANSIONS = {
    "material": {"material", "alloy", "grade", "steel", "aluminum", "aluminium"},
    "made": {"material", "alloy", "grade"},
    "tolerance": {"tolerance", "tolerances", "limit", "limits", "plus", "minus"},
    "finish": {"finish", "surface", "roughness", "ra", "anodize", "coating"},
    "revision": {"revision", "rev"},
    "dimension": {"dimension", "dimensions", "diameter", "length", "width", "height", "mm", "inch"},
    "size": {"dimension", "dimensions", "diameter", "length", "width", "height", "mm", "inch"},
    "note": {"note", "notes", "deburr", "heat", "treatment"},
}


class PDFReadError(ValueError):
    pass


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_blocks(page: pymupdf.Page, *, textpage: pymupdf.TextPage | None = None) -> list[tuple]:
    kwargs = {"sort": True}
    if textpage is not None:
        kwargs["textpage"] = textpage
    return page.get_text("blocks", **kwargs)


def _blocks_to_evidence(
    blocks: list[tuple],
    *,
    source_file: str,
    page_number: int,
    method: str,
    confidence: float,
) -> list[DrawingEvidence]:
    evidence: list[DrawingEvidence] = []
    for block_index, block in enumerate(blocks, start=1):
        if len(block) >= 7 and int(block[6]) != 0:
            continue
        text = _clean_text(str(block[4]))
        if not text:
            continue
        evidence.append(
            DrawingEvidence(
                text=text[:3000],
                source_file=source_file,
                page=page_number,
                block=block_index,
                bbox=(float(block[0]), float(block[1]), float(block[2]), float(block[3])),
                method=method,
                confidence=confidence,
            )
        )
    return evidence


def extract_drawing(pdf_bytes: bytes, source_file: str) -> DrawingDocument:
    if not pdf_bytes:
        raise PDFReadError("The drawing is empty.")
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise PDFReadError("The drawing exceeds the 50 MB safety limit.")

    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise PDFReadError(f"The PDF drawing could not be opened: {exc}") from exc

    try:
        if document.needs_pass:
            raise PDFReadError("Password-protected PDF drawings are not supported.")
        if document.page_count == 0:
            raise PDFReadError("The PDF drawing contains no pages.")
        if document.page_count > MAX_PAGES:
            raise PDFReadError(f"The drawing has {document.page_count} pages; the limit is {MAX_PAGES}.")

        evidence: list[DrawingEvidence] = []
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            evidence.extend(
                _blocks_to_evidence(
                    _extract_blocks(page),
                    source_file=source_file,
                    page_number=page_index + 1,
                    method="embedded_text",
                    confidence=0.98,
                )
            )

        text_count = sum(len(item.text) for item in evidence)
        warnings: list[str] = []
        extraction_method = "embedded_text"

        if text_count < 40 and shutil.which("tesseract"):
            ocr_evidence: list[DrawingEvidence] = []
            try:
                for page_index in range(document.page_count):
                    page = document.load_page(page_index)
                    textpage = page.get_textpage_ocr(language="eng", dpi=180, full=True)
                    ocr_evidence.extend(
                        _blocks_to_evidence(
                            _extract_blocks(page, textpage=textpage),
                            source_file=source_file,
                            page_number=page_index + 1,
                            method="ocr",
                            confidence=0.72,
                        )
                    )
            except Exception as exc:
                warnings.append(f"OCR was attempted but failed: {exc}")
            else:
                if sum(len(item.text) for item in ocr_evidence) > text_count:
                    evidence = ocr_evidence
                    text_count = sum(len(item.text) for item in evidence)
                    extraction_method = "ocr"

        page_images: list[bytes] = []
        if text_count < 40:
            for page_index in range(min(document.page_count, MAX_VISION_PAGES)):
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                page_images.append(pixmap.tobytes("png"))
            extraction_method = "vision_fallback"
            warnings.append(
                "Little or no searchable text was found. The first drawing pages will be sent as images to DeepSeek."
            )
            if document.page_count > MAX_VISION_PAGES:
                warnings.append(
                    f"Vision fallback is limited to the first {MAX_VISION_PAGES} pages."
                )

        return DrawingDocument(
            source_file=source_file,
            page_count=document.page_count,
            evidence=tuple(evidence),
            warnings=tuple(warnings),
            extraction_method=extraction_method,
            page_images=tuple(page_images),
        )
    finally:
        document.close()


def render_page_images(pdf_bytes: bytes, *, max_pages: int = 1, zoom: float = 1.8) -> tuple[bytes, ...]:
    """Render drawing pages to PNG for on-screen preview.

    This is display-only and independent of the OCR/vision fallback, so a
    drawing with searchable text can still be shown next to the record.
    """
    if not pdf_bytes:
        return ()
    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return ()
    try:
        images: list[bytes] = []
        for page_index in range(min(document.page_count, max(0, max_pages))):
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            images.append(pixmap.tobytes("png"))
        return tuple(images)
    except Exception:
        return ()
    finally:
        document.close()


def _query_terms(question: str) -> set[str]:
    terms = {
        token
        for token in re.findall(r"[a-z0-9]+", question.lower())
        if len(token) > 1 and token not in STOPWORDS
    }
    expanded = set(terms)
    for term in terms:
        expanded.update(QUERY_EXPANSIONS.get(term, set()))
    return expanded


def retrieve_drawing_evidence(
    drawing: DrawingDocument,
    question: str,
    *,
    limit: int = 8,
    max_characters: int = 7000,
) -> tuple[DrawingEvidence, ...]:
    if not drawing.evidence:
        return ()
    terms = _query_terms(question)
    document_frequency = Counter()
    block_terms: list[set[str]] = []
    for item in drawing.evidence:
        tokens = set(re.findall(r"[a-z0-9]+", item.text.lower()))
        block_terms.append(tokens)
        document_frequency.update(tokens)

    scored: list[tuple[float, int, DrawingEvidence]] = []
    for index, (item, tokens) in enumerate(zip(drawing.evidence, block_terms, strict=True)):
        overlap = terms & tokens
        score = sum(3.0 if document_frequency[token] <= 2 else 1.0 for token in overlap)
        lower_text = item.text.lower()
        score += sum(2.0 for term in terms if len(term) >= 4 and term in lower_text)
        if re.search(r"\d", item.text):
            score += 0.25
        scored.append((score, index, item))

    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    if scored[0][0] <= 0:
        scored = [(0.0, index, item) for index, item in enumerate(drawing.evidence)]

    selected: list[DrawingEvidence] = []
    characters = 0
    for _, _, item in scored:
        if len(selected) >= limit:
            break
        if selected and characters + len(item.text) > max_characters:
            continue
        selected.append(item)
        characters += len(item.text)
    return tuple(selected)

