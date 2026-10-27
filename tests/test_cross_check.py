from __future__ import annotations

from pathlib import Path

import pytest

from src.cad_reader import extract_cad
from src.cross_check import build_cross_source_audit
from src.dataset_manager import build_dataset_index, ingest_dataset
from src.excel_reader import discover_candidates, find_part, list_part_numbers
from src.pdf_reader import extract_drawing


@pytest.fixture(scope="module")
def evaluated_parts():
    bundle_path = Path("outputs/stretch_dataset/cnc_stretch_dataset.zip")
    bundle = ingest_dataset([(bundle_path.name, bundle_path.read_bytes())])
    candidate = discover_candidates(bundle.workbook.data)[0]
    parts = list_part_numbers(
        bundle.workbook.data,
        sheet_name=candidate.sheet_name,
        header_row=candidate.header_row,
        part_column=candidate.part_column,
    )
    index = build_dataset_index(bundle, parts)
    result = {}
    for part in parts:
        match = index.for_part(part)
        record = find_part(
            bundle.workbook.data,
            source_file=bundle.workbook.name,
            part_number=part,
            sheet_name=candidate.sheet_name,
            header_row=candidate.header_row,
            part_column=candidate.part_column,
        )
        drawing = extract_drawing(match.pdf_candidates[0].data, match.pdf_candidates[0].name)
        cad = extract_cad(match.cad_candidates[0].data, match.cad_candidates[0].name) if match.cad_candidates else None
        result[part] = build_cross_source_audit(record, drawing=drawing, cad=cad)
    return result


def test_consistent_part_passes_all_checks(evaluated_parts) -> None:
    report = evaluated_parts["2280"]
    assert report.status == "consistent"
    assert report.conflict_count == 0
    assert all(item.status == "pass" for item in report.findings)


def test_dimension_mismatch_is_flagged(evaluated_parts) -> None:
    report = evaluated_parts["A-2281"]
    assert report.status == "conflict"
    finding = next(item for item in report.findings if item.check == "Overall dimensions")
    assert finding.status == "conflict"
    assert "80.0" in finding.summary
    assert "82.0" in finding.summary


def test_missing_cad_is_honestly_reported(evaluated_parts) -> None:
    report = evaluated_parts["3300"]
    assert report.status == "incomplete"
    assert report.missing_count == 1
    identity = next(item for item in report.findings if item.check == "Part identity")
    assert identity.status == "pass"
    assert "PDF identifiers" in identity.summary


@pytest.fixture(scope="module")
def part_2280_sources():
    bundle_path = Path("outputs/stretch_dataset/cnc_stretch_dataset.zip")
    bundle = ingest_dataset([(bundle_path.name, bundle_path.read_bytes())])
    assert bundle.workbook is not None
    candidate = discover_candidates(bundle.workbook.data)[0]
    record = find_part(
        bundle.workbook.data,
        source_file=bundle.workbook.name,
        part_number="2280",
        sheet_name=candidate.sheet_name,
        header_row=candidate.header_row,
        part_column=candidate.part_column,
    )
    match = build_dataset_index(bundle, ("2280",)).for_part("2280")
    drawing = extract_drawing(match.pdf_candidates[0].data, match.pdf_candidates[0].name)
    cad = extract_cad(match.cad_candidates[0].data, match.cad_candidates[0].name)
    return record, drawing, cad


def test_excel_only_analysis_is_partial_not_failed(part_2280_sources) -> None:
    record, _, _ = part_2280_sources
    report = build_cross_source_audit(record, drawing=None, cad=None)
    assert report.status == "incomplete"
    assert report.missing_count == 2
    assert report.missing_sources == ("PDF drawing", "IGES model")
    assert report.conflict_count == 0


def test_pdf_only_analysis_is_partial_and_evidence_based(part_2280_sources) -> None:
    _, drawing, _ = part_2280_sources
    report = build_cross_source_audit(None, drawing=drawing, cad=None, part_number="2280")
    assert report.status == "incomplete"
    assert report.missing_count == 2
    assert next(item for item in report.findings if item.check == "Part identity").status == "pass"


def test_cad_only_analysis_reports_topology_without_guessing(part_2280_sources) -> None:
    _, _, cad = part_2280_sources
    report = build_cross_source_audit(None, drawing=None, cad=cad, part_number="2280")
    assert report.status == "incomplete"
    assert report.missing_count == 2
    assert next(item for item in report.findings if item.check == "CAD topology").status == "pass"


def test_pdf_and_cad_can_cross_check_without_excel(part_2280_sources) -> None:
    _, drawing, cad = part_2280_sources
    report = build_cross_source_audit(None, drawing=drawing, cad=cad, part_number="2280")
    assert report.status == "incomplete"
    assert report.missing_sources == ("Excel manufacturing record",)
    assert next(item for item in report.findings if item.check == "Overall dimensions").status == "pass"
