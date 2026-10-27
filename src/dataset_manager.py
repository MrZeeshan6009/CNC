from __future__ import annotations

import io
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pymupdf

from .excel_reader import normalize_identifier


MAX_ARCHIVE_BYTES = 250 * 1024 * 1024
MAX_MEMBER_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024
MAX_FILES = 250
MAX_COMPRESSION_RATIO = 250
WORKBOOK_EXTENSIONS = {".xlsx", ".xlsm", ".xls"}
PDF_EXTENSIONS = {".pdf"}
CAD_EXTENSIONS = {".igs", ".iges"}
SUPPORTED_EXTENSIONS = WORKBOOK_EXTENSIONS | PDF_EXTENSIONS | CAD_EXTENSIONS


class DatasetReadError(ValueError):
    pass


@dataclass(frozen=True)
class DatasetFile:
    name: str
    data: bytes

    @property
    def suffix(self) -> str:
        return Path(self.name).suffix.lower()


@dataclass(frozen=True)
class DatasetBundle:
    workbook: DatasetFile | None
    pdfs: tuple[DatasetFile, ...]
    cads: tuple[DatasetFile, ...]
    ignored_files: tuple[str, ...] = ()

    @property
    def file_count(self) -> int:
        return (1 if self.workbook is not None else 0) + len(self.pdfs) + len(self.cads)


@dataclass(frozen=True)
class PartAssetMatch:
    part_number: str
    pdf_candidates: tuple[DatasetFile, ...]
    cad_candidates: tuple[DatasetFile, ...]

    @property
    def pdf_status(self) -> str:
        return "matched" if len(self.pdf_candidates) == 1 else "missing" if not self.pdf_candidates else "ambiguous"

    @property
    def cad_status(self) -> str:
        return "matched" if len(self.cad_candidates) == 1 else "missing" if not self.cad_candidates else "ambiguous"


@dataclass(frozen=True)
class DatasetIndex:
    matches: tuple[PartAssetMatch, ...]
    duplicate_parts: tuple[str, ...]
    unmatched_pdfs: tuple[str, ...]
    unmatched_cads: tuple[str, ...]

    def for_part(self, part_number: str) -> PartAssetMatch:
        wanted = normalize_identifier(part_number)
        for item in self.matches:
            if item.part_number == wanted:
                return item
        raise KeyError(part_number)


def _safe_archive_member(info: zipfile.ZipInfo) -> str:
    normalized = info.filename.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise DatasetReadError(f"Unsafe path in ZIP archive: {info.filename}")
    if info.flag_bits & 0x1:
        raise DatasetReadError(f"Encrypted ZIP members are not supported: {info.filename}")
    if info.file_size > MAX_MEMBER_BYTES:
        raise DatasetReadError(f"ZIP member exceeds the 100 MB limit: {info.filename}")
    if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
        raise DatasetReadError(f"Suspicious ZIP compression ratio: {info.filename}")
    return str(path)


def _expand_zip(name: str, data: bytes) -> tuple[list[DatasetFile], list[str]]:
    if len(data) > MAX_ARCHIVE_BYTES:
        raise DatasetReadError(f"ZIP archive '{name}' exceeds the 250 MB limit.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except Exception as exc:
        raise DatasetReadError(f"ZIP archive '{name}' could not be opened: {exc}") from exc
    files: list[DatasetFile] = []
    ignored: list[str] = []
    total_size = 0
    with archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if len(members) > MAX_FILES:
            raise DatasetReadError(f"ZIP archive '{name}' contains more than {MAX_FILES} files.")
        for info in members:
            member_name = _safe_archive_member(info)
            total_size += info.file_size
            if total_size > MAX_TOTAL_BYTES:
                raise DatasetReadError("The uncompressed dataset exceeds the 500 MB limit.")
            suffix = Path(member_name).suffix.lower()
            if suffix in SUPPORTED_EXTENSIONS:
                files.append(DatasetFile(member_name, archive.read(info)))
            elif not member_name.startswith("__MACOSX/") and not Path(member_name).name.startswith("."):
                ignored.append(member_name)
    return files, ignored


def ingest_dataset(named_files: list[tuple[str, bytes]]) -> DatasetBundle:
    if not named_files:
        raise DatasetReadError("Upload a dataset ZIP or select the workbook, PDF, and IGES files.")
    expanded: list[DatasetFile] = []
    ignored: list[str] = []
    for name, data in named_files:
        if Path(name).suffix.lower() == ".zip":
            zip_files, zip_ignored = _expand_zip(name, data)
            expanded.extend(zip_files)
            ignored.extend(zip_ignored)
        elif Path(name).suffix.lower() in SUPPORTED_EXTENSIONS:
            expanded.append(DatasetFile(Path(name).name, data))
        else:
            ignored.append(name)
    if len(expanded) > MAX_FILES:
        raise DatasetReadError(f"The dataset contains more than {MAX_FILES} supported files.")
    names = [item.name.casefold() for item in expanded]
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        raise DatasetReadError(f"The dataset contains duplicate file paths: {', '.join(duplicates[:5])}")
    workbooks = [item for item in expanded if item.suffix in WORKBOOK_EXTENSIONS]
    if len(workbooks) > 1:
        raise DatasetReadError(
            "The dataset contains multiple workbooks. Keep one manufacturing workbook or upload files separately."
        )
    pdfs = tuple(sorted((item for item in expanded if item.suffix in PDF_EXTENSIONS), key=lambda item: item.name.casefold()))
    cads = tuple(sorted((item for item in expanded if item.suffix in CAD_EXTENSIONS), key=lambda item: item.name.casefold()))
    if not workbooks and not pdfs and not cads:
        raise DatasetReadError("The dataset does not contain an Excel, PDF, or IGES source file.")
    return DatasetBundle(workbooks[0] if workbooks else None, pdfs, cads, tuple(sorted(ignored)))


def _identifier_pattern(identifier: str) -> re.Pattern[str]:
    pieces = re.findall(r"[A-Z]+|\d+", normalize_identifier(identifier))
    if not pieces:
        return re.compile(r"(?!x)x")
    body = r"[-_\s.]*".join(re.escape(piece) for piece in pieces)
    return re.compile(rf"(?<![A-Z0-9]){body}(?![A-Z0-9])", re.IGNORECASE)


def _filename_matches(name: str, part_number: str) -> bool:
    return bool(_identifier_pattern(part_number).search(Path(name).stem))


def _pdf_text(pdf_file: DatasetFile) -> str:
    try:
        document = pymupdf.open(stream=pdf_file.data, filetype="pdf")
    except Exception:
        return ""
    try:
        return " ".join(document.load_page(index).get_text("text") for index in range(min(document.page_count, 5)))
    finally:
        document.close()


PART_DECLARATION_PATTERN = re.compile(
    r"PART\s*(?:NUMBER|NO\.?|#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]*)",
    re.IGNORECASE,
)
FILENAME_IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Z0-9])(?:[A-Z]+[-_. ]*)?\d+(?:[-_.]\d+)*(?![A-Z0-9])",
    re.IGNORECASE,
)
GENERIC_PART_IDENTIFIERS = {
    "EXAMPLE",
    "SAMPLE",
    "TEMPLATE",
    "UNKNOWN",
    "NONE",
    "N/A",
    "NA",
    "TBD",
}


def _filename_identifiers(name: str) -> tuple[str, ...]:
    identifiers: list[str] = []
    for match in FILENAME_IDENTIFIER_PATTERN.finditer(Path(name).stem):
        value = match.group(0).strip("-_. ")
        value = re.sub(r"^([A-Za-z]+)[_. ]+(?=\d)", r"\1-", value)
        normalized = normalize_identifier(value)
        if normalized and normalized not in identifiers:
            identifiers.append(normalized)
    return tuple(identifiers)


def discover_asset_part_numbers(bundle: DatasetBundle) -> tuple[str, ...]:
    """Discover conservative part-number candidates without requiring Excel.

    PDF title-block declarations take precedence. Filenames are used as a
    fallback for drawings and as the only portable identifier available in
    ordinary IGES files. Uncertain datasets can still be mapped manually in
    the UI.
    """
    identifiers: list[str] = []
    for item in bundle.pdfs:
        declared = [
            normalize_identifier(value)
            for value in PART_DECLARATION_PATTERN.findall(_pdf_text(item))
            if normalize_identifier(value) not in GENERIC_PART_IDENTIFIERS
        ]
        candidates = [value for value in declared if value] or list(_filename_identifiers(item.name))
        for value in candidates:
            if value not in identifiers:
                identifiers.append(value)
    for item in bundle.cads:
        for value in _filename_identifiers(item.name):
            if value not in identifiers:
                identifiers.append(value)
    return tuple(identifiers)


def _most_specific(parts: list[str]) -> list[str]:
    if len(parts) <= 1:
        return parts
    compact_lengths = {
        part: len(re.sub(r"[^A-Z0-9]", "", part.upper())) for part in parts
    }
    longest = max(compact_lengths.values())
    return [part for part in parts if compact_lengths[part] == longest]


def build_dataset_index(
    bundle: DatasetBundle,
    part_numbers: tuple[str, ...],
    *,
    allow_single_file_fallback: bool = False,
) -> DatasetIndex:
    normalized = tuple(normalize_identifier(value) for value in part_numbers if normalize_identifier(value))
    counts = Counter(normalized)
    unique_parts = tuple(dict.fromkeys(normalized))
    duplicate_parts = tuple(sorted(part for part, count in counts.items() if count > 1))

    pdf_assignments: dict[str, list[DatasetFile]] = {part: [] for part in unique_parts}
    cad_assignments: dict[str, list[DatasetFile]] = {part: [] for part in unique_parts}
    assigned_pdfs: set[str] = set()
    assigned_cads: set[str] = set()

    for item in bundle.pdfs:
        filename_parts = _most_specific([part for part in unique_parts if _filename_matches(item.name, part)])
        matched_parts = filename_parts
        if not matched_parts:
            text = _pdf_text(item)
            matched_parts = _most_specific([part for part in unique_parts if _identifier_pattern(part).search(text)])
        for part in matched_parts:
            pdf_assignments[part].append(item)
            assigned_pdfs.add(item.name)

    for item in bundle.cads:
        matched_parts = _most_specific([part for part in unique_parts if _filename_matches(item.name, part)])
        for part in matched_parts:
            cad_assignments[part].append(item)
            assigned_cads.add(item.name)

    # When the user supplied one part and one source file, accepting that
    # explicit one-to-one mapping is safer than inventing an identifier from
    # geometry. The audit still reports that filename identity is unverified.
    if allow_single_file_fallback and len(unique_parts) == 1:
        only_part = unique_parts[0]
        if len(bundle.pdfs) == 1 and not pdf_assignments[only_part]:
            pdf_assignments[only_part].append(bundle.pdfs[0])
            assigned_pdfs.add(bundle.pdfs[0].name)
        if len(bundle.cads) == 1 and not cad_assignments[only_part]:
            cad_assignments[only_part].append(bundle.cads[0])
            assigned_cads.add(bundle.cads[0].name)

    matches = tuple(
        PartAssetMatch(
            part_number=part,
            pdf_candidates=tuple(pdf_assignments[part]),
            cad_candidates=tuple(cad_assignments[part]),
        )
        for part in unique_parts
    )
    return DatasetIndex(
        matches=matches,
        duplicate_parts=duplicate_parts,
        unmatched_pdfs=tuple(item.name for item in bundle.pdfs if item.name not in assigned_pdfs),
        unmatched_cads=tuple(item.name for item in bundle.cads if item.name not in assigned_cads),
    )
