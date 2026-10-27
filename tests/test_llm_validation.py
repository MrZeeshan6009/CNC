from src.llm_client import validate_answer
from src.models import CADDocument, DrawingDocument, DrawingEvidence, Evidence, PartRecord


def _record() -> PartRecord:
    evidence = Evidence(
        field="Material",
        value="Aluminum 6061",
        source_file="sample.xlsx",
        sheet_name="Parts",
        cell="B2",
    )
    return PartRecord(
        part_number="2280",
        source_file="sample.xlsx",
        sheet_name="Parts",
        excel_row=2,
        values={"Part Number": 2280, "Material": "Aluminum 6061"},
        evidence=(evidence,),
    )


def test_invalid_model_citations_are_removed() -> None:
    result = validate_answer(
        {
            "answer": "It is titanium.",
            "confidence": "high",
            "evidence": [
                {
                    "source_type": "excel",
                    "source_file": "made-up.xlsx",
                    "location": "Parts!Z99",
                    "field": "Material",
                }
            ],
            "warnings": [],
        },
        _record(),
    )
    assert result["evidence"] == []
    assert result["confidence"] == "low"
    assert result["warnings"]


def test_valid_model_citation_is_kept() -> None:
    result = validate_answer(
        {
            "answer": "The material is Aluminum 6061.",
            "confidence": "high",
            "evidence": [
                {
                    "source_type": "excel",
                    "source_file": "sample.xlsx",
                    "location": "Parts!B2",
                    "field": "Material",
                }
            ],
            "warnings": [],
        },
        _record(),
    )
    assert result["confidence"] == "high"
    assert result["evidence"][0]["location"] == "Parts!B2"


def test_valid_pdf_citation_is_kept() -> None:
    evidence = DrawingEvidence(
        text="SURFACE FINISH: Ra 1.6",
        source_file="2280.pdf",
        page=1,
        block=1,
        bbox=(10, 10, 100, 30),
    )
    drawing = DrawingDocument(
        source_file="2280.pdf",
        page_count=1,
        evidence=(evidence,),
        warnings=(),
        extraction_method="embedded_text",
    )
    result = validate_answer(
        {
            "answer": "The surface finish is Ra 1.6.",
            "confidence": "high",
            "evidence": [
                {
                    "source_type": "pdf",
                    "source_file": "2280.pdf",
                    "location": "page 1",
                    "field": "drawing_text",
                }
            ],
            "warnings": [],
        },
        _record(),
        drawing=drawing,
        drawing_evidence=(evidence,),
    )
    assert result["confidence"] == "high"
    assert result["evidence"][0]["source_type"] == "pdf"


def test_pdf_citation_is_valid_without_an_excel_record() -> None:
    evidence = DrawingEvidence(
        text="MATERIAL: ALUMINUM 6061-T6",
        source_file="2280.pdf",
        page=1,
        block=1,
        bbox=(10, 10, 100, 30),
    )
    drawing = DrawingDocument(
        source_file="2280.pdf",
        page_count=1,
        evidence=(evidence,),
        warnings=(),
        extraction_method="embedded_text",
    )
    result = validate_answer(
        {
            "answer": "The drawing specifies Aluminum 6061-T6.",
            "confidence": "high",
            "evidence": [{
                "source_type": "pdf",
                "source_file": "2280.pdf",
                "location": "page 1",
                "field": "drawing_text",
            }],
            "warnings": [],
        },
        None,
        drawing=drawing,
        drawing_evidence=(evidence,),
    )
    assert result["confidence"] == "high"
    assert result["evidence"][0]["source_type"] == "pdf"


def test_valid_cad_citation_is_kept() -> None:
    cad = CADDocument(
        source_file="2280.igs",
        units="mm",
        bounding_box_mm=(120.0, 75.0, 10.0),
        volume_mm3=86858.4,
        surface_area_mm2=22528.3,
        center_of_mass_mm=(60.0, 37.5, 5.0),
        solid_count=1,
        shell_count=1,
        face_count=10,
        edge_count=48,
        model_valid=True,
        cylindrical_features=(),
        warnings=(),
    )
    result = validate_answer(
        {
            "answer": "The bounding box is 120 by 75 by 10 mm.",
            "confidence": "high",
            "evidence": [
                {
                    "source_type": "cad_metadata",
                    "source_file": "2280.igs",
                    "location": "model geometry",
                    "field": "bounding_box_mm.x",
                }
            ],
            "warnings": [],
        },
        _record(),
        cad=cad,
    )
    assert result["confidence"] == "high"
    assert result["evidence"][0]["field"] == "bounding_box_mm"

