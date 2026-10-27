from __future__ import annotations

import json
from types import SimpleNamespace

from src.llm_client import answer_question
from src.models import DrawingDocument, DrawingEvidence


def test_answer_question_supports_pdf_without_excel(monkeypatch) -> None:
    evidence = DrawingEvidence(
        text="PART NUMBER: 2280 MATERIAL: ALUMINUM 6061-T6",
        source_file="2280_drawing.pdf",
        page=1,
        block=1,
        bbox=(0.0, 0.0, 200.0, 40.0),
    )
    drawing = DrawingDocument(
        source_file="2280_drawing.pdf",
        page_count=1,
        evidence=(evidence,),
        warnings=(),
        extraction_method="embedded_text",
    )
    captured: dict = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            content = json.dumps(
                {
                    "answer": "The drawing specifies Aluminum 6061-T6.",
                    "evidence": [{
                        "source_type": "pdf",
                        "source_file": "2280_drawing.pdf",
                        "location": "page 1",
                        "field": "drawing_text",
                    }],
                    "confidence": "high",
                    "warnings": ["Excel and IGES were not supplied."],
                }
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

    class FakeClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("src.llm_client.OpenAI", lambda **_: FakeClient())
    result = answer_question(
        None,
        "What material is specified?",
        part_number="2280",
        drawing=drawing,
        drawing_evidence=(evidence,),
        api_key="test-key",
    )

    payload = json.loads(captured["messages"][1]["content"])
    assert payload["selected_part_number"] == "2280"
    assert "selected_part_excel" not in payload
    assert payload["selected_part_drawing"]["source_file"] == "2280_drawing.pdf"
    assert result["confidence"] == "high"
    assert result["evidence"][0]["source_type"] == "pdf"

