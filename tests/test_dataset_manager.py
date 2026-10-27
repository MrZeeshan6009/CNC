from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
import pymupdf

from src.dataset_manager import (
    DatasetBundle,
    DatasetFile,
    DatasetReadError,
    build_dataset_index,
    discover_asset_part_numbers,
    ingest_dataset,
)


BUNDLE_PATH = Path("outputs/stretch_dataset/cnc_stretch_dataset.zip")


def test_ingests_and_indexes_stretch_bundle() -> None:
    bundle = ingest_dataset([(BUNDLE_PATH.name, BUNDLE_PATH.read_bytes())])
    assert len(bundle.pdfs) == 3
    assert len(bundle.cads) == 2
    index = build_dataset_index(bundle, ("2280", "A-2281", "3300"))
    assert index.for_part("2280").pdf_status == "matched"
    assert index.for_part("2280").cad_status == "matched"
    assert index.for_part("A-2281").cad_status == "matched"
    assert index.for_part("3300").cad_status == "missing"


def test_rejects_zip_path_traversal() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("../manufacturing_records.xlsx", b"unsafe")
    with pytest.raises(DatasetReadError, match="Unsafe path"):
        ingest_dataset([("unsafe.zip", output.getvalue())])


def test_rejects_multiple_workbooks() -> None:
    with pytest.raises(DatasetReadError, match="multiple workbooks"):
        ingest_dataset(
            [
                ("one.xlsx", b"one"),
                ("two.xlsx", b"two"),
            ]
        )


def test_reports_ambiguous_asset_candidates() -> None:
    bundle = DatasetBundle(
        workbook=DatasetFile("records.xlsx", b"workbook"),
        pdfs=(DatasetFile("2280_a.pdf", b""), DatasetFile("2280_b.pdf", b"")),
        cads=(),
    )
    index = build_dataset_index(bundle, ("2280",))
    assert index.for_part("2280").pdf_status == "ambiguous"


def test_more_specific_alphanumeric_part_wins_filename_match() -> None:
    bundle = DatasetBundle(
        workbook=DatasetFile("records.xlsx", b"workbook"),
        pdfs=(),
        cads=(DatasetFile("A-2281_model.igs", b""),),
    )
    index = build_dataset_index(bundle, ("2281", "A-2281"))
    assert index.for_part("2281").cad_status == "missing"
    assert index.for_part("A-2281").cad_status == "matched"


def test_duplicate_part_numbers_are_reported() -> None:
    bundle = DatasetBundle(
        workbook=DatasetFile("records.xlsx", b"workbook"),
        pdfs=(),
        cads=(),
    )
    index = build_dataset_index(bundle, ("2280", "2280"))
    assert index.duplicate_parts == ("2280",)


def test_pdf_only_dataset_is_accepted_and_part_is_discovered() -> None:
    pdf_path = Path("output/pdf/stretch_dataset/A-2281_revB.pdf")
    bundle = ingest_dataset([(pdf_path.name, pdf_path.read_bytes())])
    assert bundle.workbook is None
    assert discover_asset_part_numbers(bundle) == ("A-2281",)
    match = build_dataset_index(bundle, ("A-2281",)).for_part("A-2281")
    assert match.pdf_status == "matched"
    assert match.cad_status == "missing"


def test_cad_only_dataset_is_accepted_and_part_is_discovered() -> None:
    cad_path = Path("outputs/stretch_dataset/cad/2280_model.igs")
    bundle = ingest_dataset([(cad_path.name, cad_path.read_bytes())])
    assert bundle.workbook is None
    assert discover_asset_part_numbers(bundle) == ("2280",)
    match = build_dataset_index(bundle, ("2280",)).for_part("2280")
    assert match.pdf_status == "missing"
    assert match.cad_status == "matched"


def test_single_unlabelled_asset_can_be_explicitly_mapped() -> None:
    bundle = DatasetBundle(
        workbook=None,
        pdfs=(),
        cads=(DatasetFile("model.igs", b"geometry"),),
    )
    match = build_dataset_index(
        bundle,
        ("MANUAL-42",),
        allow_single_file_fallback=True,
    ).for_part("MANUAL-42")
    assert match.cad_status == "matched"


def test_unmatched_single_asset_is_not_silently_associated() -> None:
    bundle = DatasetBundle(
        workbook=None,
        pdfs=(DatasetFile("2280_drawing.pdf", b""),),
        cads=(DatasetFile("unrelated_bearing.igs", b"geometry"),),
    )
    match = build_dataset_index(bundle, ("2280",)).for_part("2280")
    assert match.pdf_status == "matched"
    assert match.cad_status == "missing"


def test_rejects_dataset_without_supported_sources() -> None:
    with pytest.raises(DatasetReadError, match="does not contain an Excel, PDF, or IGES"):
        ingest_dataset([("notes.txt", b"not a supported engineering source")])


def test_placeholder_pdf_part_number_is_not_indexed() -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "PART NUMBER: EXAMPLE")
    pdf_bytes = document.tobytes()
    document.close()
    bundle = ingest_dataset([("training_drawing.pdf", pdf_bytes)])
    assert discover_asset_part_numbers(bundle) == ()
