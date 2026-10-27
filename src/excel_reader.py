from __future__ import annotations

import io
import re
from pathlib import Path
from typing import BinaryIO

import pandas as pd
from openpyxl.utils import get_column_letter

from .models import Evidence, PartRecord, WorkbookCandidate


PART_COLUMN_ALIASES = {
    "partnumber",
    "partno",
    "partid",
    "partcode",
    "componentnumber",
    "componentno",
    "componentid",
    "itemnumber",
    "itemno",
    "itemid",
}


class WorkbookReadError(ValueError):
    pass


class PartNotFoundError(LookupError):
    pass


class DuplicatePartError(LookupError):
    pass


def normalize_label(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())


def normalize_identifier(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0+", text):
        return text.split(".", 1)[0]
    return re.sub(r"\s+", "", text).upper()


def _source_bytes(source: bytes | BinaryIO | str | Path) -> bytes:
    if isinstance(source, bytes):
        return source
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()
    if hasattr(source, "getvalue"):
        return source.getvalue()
    if hasattr(source, "seek"):
        source.seek(0)
    return source.read()


def _excel_file(source: bytes | BinaryIO | str | Path) -> pd.ExcelFile:
    try:
        return pd.ExcelFile(io.BytesIO(_source_bytes(source)))
    except Exception as exc:
        raise WorkbookReadError(f"The workbook could not be opened: {exc}") from exc


def _unique_columns(values: list[object]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for index, value in enumerate(values, start=1):
        base = str(value).strip() if not pd.isna(value) else ""
        if not base or base.lower().startswith("unnamed"):
            base = f"Column {index}"
        seen[base] = seen.get(base, 0) + 1
        result.append(base if seen[base] == 1 else f"{base} ({seen[base]})")
    return result


def discover_candidates(
    source: bytes | BinaryIO | str | Path,
    *,
    max_header_rows: int = 20,
) -> list[WorkbookCandidate]:
    workbook = _excel_file(source)
    candidates: list[WorkbookCandidate] = []

    for sheet_name in workbook.sheet_names:
        try:
            preview = pd.read_excel(
                workbook,
                sheet_name=sheet_name,
                header=None,
                nrows=max_header_rows + 5,
                dtype=object,
            )
        except Exception:
            continue

        if preview.empty:
            continue

        for row_index in range(min(max_header_rows, len(preview))):
            row = preview.iloc[row_index].tolist()
            normalized = [normalize_label(value) for value in row]
            nonempty = sum(bool(value) for value in normalized)
            if nonempty < 2:
                continue

            for column_index, label in enumerate(normalized):
                if label not in PART_COLUMN_ALIASES:
                    continue
                columns = _unique_columns(row)
                part_column = columns[column_index]
                data_rows = max(len(preview) - row_index - 1, 0)
                score = 100.0 - (row_index * 2.0) + min(nonempty, 10)
                candidates.append(
                    WorkbookCandidate(
                        sheet_name=sheet_name,
                        header_row=row_index,
                        part_column=part_column,
                        score=score,
                        columns=tuple(columns),
                        row_count=data_rows,
                    )
                )

    return sorted(candidates, key=lambda item: (-item.score, item.sheet_name, item.header_row))


def list_sheets(source: bytes | BinaryIO | str | Path) -> list[str]:
    return _excel_file(source).sheet_names


def preview_sheet(
    source: bytes | BinaryIO | str | Path,
    sheet_name: str,
    *,
    header_row: int = 0,
    nrows: int = 20,
) -> pd.DataFrame:
    workbook = _excel_file(source)
    try:
        frame = pd.read_excel(
            workbook,
            sheet_name=sheet_name,
            header=header_row,
            nrows=nrows,
            dtype=object,
        )
    except Exception as exc:
        raise WorkbookReadError(f"Sheet '{sheet_name}' could not be read: {exc}") from exc
    frame.columns = _unique_columns(list(frame.columns))
    return frame.dropna(how="all")


def list_part_numbers(
    source: bytes | BinaryIO | str | Path,
    *,
    sheet_name: str,
    header_row: int,
    part_column: str,
) -> tuple[str, ...]:
    workbook = _excel_file(source)
    try:
        frame = pd.read_excel(
            workbook,
            sheet_name=sheet_name,
            header=header_row,
            dtype=object,
        )
    except Exception as exc:
        raise WorkbookReadError(f"Sheet '{sheet_name}' could not be read: {exc}") from exc
    frame.columns = _unique_columns(list(frame.columns))
    if part_column not in frame.columns:
        raise WorkbookReadError(f"Column '{part_column}' is not present in sheet '{sheet_name}'.")
    return tuple(
        identifier
        for identifier in frame[part_column].map(normalize_identifier)
        if identifier
    )


def find_part(
    source: bytes | BinaryIO | str | Path,
    *,
    source_file: str,
    part_number: str,
    sheet_name: str,
    header_row: int,
    part_column: str,
) -> PartRecord:
    workbook = _excel_file(source)
    try:
        frame = pd.read_excel(
            workbook,
            sheet_name=sheet_name,
            header=header_row,
            dtype=object,
        )
    except Exception as exc:
        raise WorkbookReadError(f"Sheet '{sheet_name}' could not be read: {exc}") from exc

    frame.columns = _unique_columns(list(frame.columns))
    if part_column not in frame.columns:
        raise WorkbookReadError(f"Column '{part_column}' is not present in sheet '{sheet_name}'.")

    wanted = normalize_identifier(part_number)
    if not wanted:
        raise ValueError("Enter a part number.")

    matches = frame[part_column].map(normalize_identifier) == wanted
    match_indexes = frame.index[matches].tolist()
    if not match_indexes:
        raise PartNotFoundError(
            f"Part '{part_number}' was not found in column '{part_column}' on sheet '{sheet_name}'."
        )
    if len(match_indexes) > 1:
        excel_rows = [header_row + index + 2 for index in match_indexes]
        raise DuplicatePartError(
            f"Part '{part_number}' appears more than once in sheet '{sheet_name}' "
            f"at Excel rows {excel_rows}. Select a unique record before analysis."
        )

    index = match_indexes[0]
    excel_row = header_row + index + 2
    raw_row = frame.loc[index]
    values: dict[str, object] = {}
    evidence: list[Evidence] = []

    for column_position, (column, value) in enumerate(raw_row.items(), start=1):
        if pd.isna(value):
            clean_value: object = None
        elif hasattr(value, "isoformat") and not isinstance(value, str):
            clean_value = value.isoformat()
        elif hasattr(value, "item"):
            clean_value = value.item()
        else:
            clean_value = value

        values[str(column)] = clean_value
        if clean_value is not None:
            evidence.append(
                Evidence(
                    field=str(column),
                    value=clean_value,
                    source_file=source_file,
                    sheet_name=sheet_name,
                    cell=f"{get_column_letter(column_position)}{excel_row}",
                )
            )

    return PartRecord(
        part_number=normalize_identifier(raw_row[part_column]),
        source_file=source_file,
        sheet_name=sheet_name,
        excel_row=excel_row,
        values=values,
        evidence=tuple(evidence),
    )

