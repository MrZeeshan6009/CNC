from __future__ import annotations

import re
from pathlib import Path

from .excel_reader import normalize_identifier, normalize_label
from .models import (
    AuditEvidence,
    AuditFinding,
    AuditReport,
    CADDocument,
    DrawingDocument,
    DrawingEvidence,
    PartRecord,
)


DIMENSION_PATTERN = re.compile(
    r"(?<![A-Z0-9.])(\d+(?:\.\d+)?)\s*(?:\+/-|±)\s*(\d+(?:\.\d+)?)\s*MM",
    re.IGNORECASE,
)
HOLE_PATTERN = re.compile(
    r"(\d+)\s*X\s*(?:DIA|DIAMETER|[Ø⌀])\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
PART_PATTERN = re.compile(
    r"PART\s*(?:NUMBER|NO\.?|#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]*)",
    re.IGNORECASE,
)
MATERIAL_PATTERN = re.compile(r"MATERIAL\s*:\s*([^\n;]+)", re.IGNORECASE)


def _drawing_text(drawing: DrawingDocument) -> str:
    return "\n".join(item.text for item in drawing.evidence)


def _pdf_evidence(item: DrawingEvidence, field: str, value: object) -> AuditEvidence:
    return AuditEvidence("pdf", item.source_file, item.location, field, value)


def _cad_evidence(cad: CADDocument, field: str, value: object) -> AuditEvidence:
    return AuditEvidence("cad", cad.source_file, "model geometry", field, value)


def _excel_field(record: PartRecord, label_fragment: str) -> tuple[object | None, AuditEvidence | None]:
    wanted = normalize_label(label_fragment)
    for item in record.evidence:
        if wanted in normalize_label(item.field):
            return item.value, AuditEvidence(
                "excel",
                item.source_file,
                f"{item.sheet_name}!{item.cell}",
                item.field,
                item.value,
            )
    return None, None


def _normalized_material(value: object) -> str:
    text = str(value).upper().replace("ALUMINIUM", "ALUMINUM")
    return re.sub(r"[^A-Z0-9]+", "", text)


def _drawing_material(drawing: DrawingDocument) -> tuple[str | None, DrawingEvidence | None]:
    for item in drawing.evidence:
        match = MATERIAL_PATTERN.search(item.text)
        if match:
            return match.group(1).strip(), item
    return None, None


def _drawing_dimensions(drawing: DrawingDocument) -> list[tuple[float, float, DrawingEvidence]]:
    values: list[tuple[float, float, DrawingEvidence]] = []
    seen: set[tuple[float, float]] = set()
    for item in drawing.evidence:
        for match in DIMENSION_PATTERN.finditer(item.text):
            pair = (float(match.group(1)), float(match.group(2)))
            if pair not in seen:
                seen.add(pair)
                values.append((pair[0], pair[1], item))
    return values


def _drawing_holes(drawing: DrawingDocument) -> tuple[int, float, DrawingEvidence] | None:
    for item in drawing.evidence:
        match = HOLE_PATTERN.search(item.text)
        if match:
            return int(match.group(1)), float(match.group(2)), item
    return None


def build_cross_source_audit(
    record: PartRecord | None,
    *,
    drawing: DrawingDocument | None,
    cad: CADDocument | None,
    part_number: str | None = None,
) -> AuditReport:
    selected_part = normalize_identifier(part_number or (record.part_number if record is not None else ""))
    if not selected_part:
        raise ValueError("A part number is required for source analysis.")
    findings: list[AuditFinding] = []
    available: list[str] = []
    missing: list[str] = []
    if record is not None:
        available.append("Excel")
    else:
        missing.append("Excel manufacturing record")
    if drawing is not None:
        available.append("PDF")
    else:
        missing.append("PDF drawing")
    if cad is not None:
        available.append("IGES")
    else:
        missing.append("IGES model")
    coverage_status = "missing" if missing else "pass"
    coverage_summary = (
        f"Available sources: {', '.join(available)}. Missing: {', '.join(missing)}."
        if missing
        else "Excel, PDF, and IGES sources are available for this part."
    )
    findings.append(AuditFinding("Source coverage", coverage_status, coverage_summary))

    wanted_part = selected_part
    identity_evidence: list[AuditEvidence] = []
    identity_issues: list[str] = []
    identity_verified: list[str] = []
    identity_conflict = False
    if record is not None:
        excel_part = normalize_identifier(record.part_number)
        identity_evidence.append(
            AuditEvidence(
                "excel",
                record.source_file,
                f"{record.sheet_name}!row {record.excel_row}",
                "part_number",
                excel_part,
            )
        )
        if excel_part != wanted_part:
            identity_issues.append(f"Excel identifies part {excel_part}, not {wanted_part}")
            identity_conflict = True
        else:
            identity_verified.append("Excel")
    if drawing is not None:
        found_parts: list[tuple[str, DrawingEvidence]] = []
        for item in drawing.evidence:
            found_parts.extend((normalize_identifier(match.group(1)), item) for match in PART_PATTERN.finditer(item.text))
        if found_parts:
            part, item = found_parts[0]
            identity_evidence.append(_pdf_evidence(item, "part_number", part))
            if part != wanted_part:
                identity_issues.append(f"PDF identifies part {part}, not {wanted_part}")
                identity_conflict = True
            else:
                identity_verified.append("PDF")
        else:
            identity_issues.append("PDF part number could not be verified")
    if cad is not None:
        filename = Path(cad.source_file).stem
        compact_filename = re.sub(r"[^A-Z0-9]", "", filename.upper())
        compact_part = re.sub(r"[^A-Z0-9]", "", wanted_part.upper())
        identity_evidence.append(_cad_evidence(cad, "source_file", cad.source_file))
        if compact_part not in compact_filename:
            identity_issues.append("CAD filename does not contain the selected part number")
        else:
            identity_verified.append("CAD")
    if not identity_verified and not identity_issues:
        identity_issues.append("No PDF or CAD identifier was available to verify")
    if identity_conflict:
        identity_status = "conflict"
    elif identity_issues:
        identity_status = "warning"
    else:
        identity_status = "pass"
    findings.append(
        AuditFinding(
            "Part identity",
            identity_status,
            "; ".join(identity_issues)
            if identity_issues
            else f"{' and '.join(identity_verified)} identifiers agree with part {wanted_part}.",
            tuple(identity_evidence),
        )
    )

    if record is not None or drawing is not None:
        excel_material, excel_material_evidence = _excel_field(record, "material") if record is not None else (None, None)
        pdf_material, pdf_material_item = _drawing_material(drawing) if drawing is not None else (None, None)
        evidence: list[AuditEvidence] = []
        if excel_material_evidence:
            evidence.append(excel_material_evidence)
        if pdf_material_item and pdf_material is not None:
            evidence.append(_pdf_evidence(pdf_material_item, "material", pdf_material))
        if record is None:
            findings.append(
                AuditFinding(
                    "Material",
                    "warning",
                    "Material is available only from the PDF and cannot be cross-checked against Excel."
                    if pdf_material is not None
                    else "Material could not be extracted from the supplied PDF.",
                    tuple(evidence),
                )
            )
        elif drawing is None:
            findings.append(
                AuditFinding(
                    "Material",
                    "warning",
                    "Material is available only from Excel and cannot be cross-checked against a drawing."
                    if excel_material is not None
                    else "Material is not present in the supplied Excel record.",
                    tuple(evidence),
                )
            )
        elif excel_material is None or pdf_material is None:
            findings.append(
                AuditFinding("Material", "warning", "Material could not be compared across Excel and PDF.", tuple(evidence))
            )
        elif _normalized_material(excel_material) == _normalized_material(pdf_material):
            findings.append(
                AuditFinding("Material", "pass", f"Excel and PDF both specify {excel_material}.", tuple(evidence))
            )
        else:
            findings.append(
                AuditFinding(
                    "Material",
                    "conflict",
                    f"Excel specifies {excel_material}; PDF specifies {pdf_material}.",
                    tuple(evidence),
                )
            )

    if drawing is not None and cad is not None:
        dimensions = _drawing_dimensions(drawing)
        if len(dimensions) >= 3:
            selected = sorted(dimensions, key=lambda item: item[0])[-3:]
            drawing_values = sorted((value, tolerance, item) for value, tolerance, item in selected)
            cad_values = sorted(cad.bounding_box_mm)
            differences = [abs(drawing_values[index][0] - cad_values[index]) for index in range(3)]
            within = all(
                difference <= drawing_values[index][1] + 0.01
                for index, difference in enumerate(differences)
            )
            evidence = tuple(
                [_pdf_evidence(item, "overall_dimension_mm", value) for value, _, item in drawing_values]
                + [_cad_evidence(cad, "bounding_box_mm", cad.bounding_box_mm)]
            )
            findings.append(
                AuditFinding(
                    "Overall dimensions",
                    "pass" if within else "conflict",
                    (
                        f"Drawing dimensions {tuple(value for value, _, _ in drawing_values)} mm agree with CAD bounding box {tuple(cad_values)} mm."
                        if within
                        else f"Drawing dimensions {tuple(value for value, _, _ in drawing_values)} mm do not agree with CAD bounding box {tuple(cad_values)} mm within drawing tolerances."
                    ),
                    evidence,
                )
            )
        else:
            findings.append(
                AuditFinding("Overall dimensions", "warning", "Three overall drawing dimensions could not be extracted reliably.")
            )

        drawing_holes = _drawing_holes(drawing)
        if drawing_holes:
            count, diameter, drawing_item = drawing_holes
            matching_features = [
                feature
                for feature in cad.cylindrical_features
                if abs(feature.diameter_mm - diameter) <= 0.05 and feature.candidate_count == count
            ]
            evidence = (
                _pdf_evidence(drawing_item, "hole_callout", f"{count} x diameter {diameter} mm"),
                _cad_evidence(cad, "cylindrical_features", [item.to_dict() for item in cad.cylindrical_features]),
            )
            findings.append(
                AuditFinding(
                    "Hole candidates",
                    "pass" if matching_features else "conflict",
                    (
                        f"Drawing callout {count} x diameter {diameter:g} mm matches a CAD cylindrical candidate group."
                        if matching_features
                        else f"Drawing callout {count} x diameter {diameter:g} mm has no matching CAD cylindrical candidate group."
                    ),
                    evidence,
                )
            )
        elif cad.cylindrical_features:
            findings.append(
                AuditFinding(
                    "Hole candidates",
                    "warning",
                    "CAD contains cylindrical candidates, but no quantity-and-diameter hole callout was extracted from the PDF.",
                    (_cad_evidence(cad, "cylindrical_features", [item.to_dict() for item in cad.cylindrical_features]),),
                )
            )
        else:
            findings.append(AuditFinding("Hole candidates", "pass", "No drawing hole callout or CAD cylindrical candidate was found."))

    if cad is not None:
        findings.append(
            AuditFinding(
                "CAD topology",
                "pass" if cad.model_valid else "conflict",
                "OpenCascade reports valid model topology." if cad.model_valid else "OpenCascade reports invalid or incomplete model topology.",
                (_cad_evidence(cad, "model_valid", cad.model_valid),),
            )
        )

    statuses = {item.status for item in findings}
    if "conflict" in statuses:
        overall = "conflict"
    elif "missing" in statuses:
        overall = "incomplete"
    elif "warning" in statuses:
        overall = "review"
    else:
        overall = "consistent"
    return AuditReport(selected_part, overall, tuple(findings), tuple(missing))
