from __future__ import annotations

import io

import pandas as pd
import pytest

from src.excel_reader import (
    DuplicatePartError,
    PartNotFoundError,
    discover_candidates,
    find_part,
    normalize_identifier,
)


@pytest.fixture()
def workbook_bytes() -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame([["Manufacturing export"], ["Generated for testing"]]).to_excel(
            writer, sheet_name="ReadMe", index=False, header=False
        )
        pd.DataFrame(
            {
                "Component ID": [2280, "A-2281", 2282],
                "Material Grade": ["Aluminum 6061-T6", "AISI 1045", "SS 304"],
                "Machine": ["VMC-01", "LATHE-02", "VMC-03"],
                "Cycle Time (min)": [18, 12, 26],
            }
        ).to_excel(writer, sheet_name="Production", index=False, startrow=2)
    return output.getvalue()


def test_discovers_sheet_header_and_part_column(workbook_bytes: bytes) -> None:
    candidates = discover_candidates(workbook_bytes)
    assert candidates
    assert candidates[0].sheet_name == "Production"
    assert candidates[0].header_row == 2
    assert candidates[0].part_column == "Component ID"


def test_finds_numeric_part_and_preserves_evidence(workbook_bytes: bytes) -> None:
    record = find_part(
        workbook_bytes,
        source_file="sample.xlsx",
        part_number="2280",
        sheet_name="Production",
        header_row=2,
        part_column="Component ID",
    )
    assert record.part_number == "2280"
    assert record.values["Material Grade"] == "Aluminum 6061-T6"
    assert record.excel_row == 4
    assert any(item.cell == "B4" and item.field == "Material Grade" for item in record.evidence)


def test_identifier_normalization() -> None:
    assert normalize_identifier(2280.0) == "2280"
    assert normalize_identifier(" a-2281 ") == "A-2281"


def test_missing_part_raises(workbook_bytes: bytes) -> None:
    with pytest.raises(PartNotFoundError):
        find_part(
            workbook_bytes,
            source_file="sample.xlsx",
            part_number="9999",
            sheet_name="Production",
            header_row=2,
            part_column="Component ID",
        )


def test_duplicate_part_is_rejected() -> None:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame({"Part No": [2280, 2280], "Material": ["A", "B"]}).to_excel(
            writer, index=False
        )

    with pytest.raises(DuplicatePartError):
        find_part(
            output.getvalue(),
            source_file="duplicate.xlsx",
            part_number="2280",
            sheet_name="Sheet1",
            header_row=0,
            part_column="Part No",
        )

