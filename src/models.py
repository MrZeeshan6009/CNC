from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class WorkbookCandidate:
    sheet_name: str
    header_row: int
    part_column: str
    score: float
    columns: tuple[str, ...]
    row_count: int


@dataclass(frozen=True)
class Evidence:
    field: str
    value: Any
    source_file: str
    sheet_name: str
    cell: str
    method: str = "direct_cell"
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PartRecord:
    part_number: str
    source_file: str
    sheet_name: str
    excel_row: int
    values: dict[str, Any]
    evidence: tuple[Evidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "part_number": self.part_number,
            "source_file": self.source_file,
            "sheet_name": self.sheet_name,
            "excel_row": self.excel_row,
            "values": self.values,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class DrawingEvidence:
    text: str
    source_file: str
    page: int
    block: int
    bbox: tuple[float, float, float, float]
    method: str = "embedded_text"
    confidence: float = 0.98

    @property
    def location(self) -> str:
        return f"page {self.page}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "source_file": self.source_file,
            "page": self.page,
            "block": self.block,
            "location": self.location,
            "bbox": list(self.bbox),
            "method": self.method,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class DrawingDocument:
    source_file: str
    page_count: int
    evidence: tuple[DrawingEvidence, ...]
    warnings: tuple[str, ...]
    extraction_method: str
    page_images: tuple[bytes, ...] = ()

    @property
    def text_character_count(self) -> int:
        return sum(len(item.text) for item in self.evidence)

    @property
    def has_searchable_text(self) -> bool:
        return self.text_character_count >= 40

    def to_dict(self, evidence: tuple[DrawingEvidence, ...] | None = None) -> dict[str, Any]:
        selected = evidence if evidence is not None else self.evidence
        return {
            "source_file": self.source_file,
            "page_count": self.page_count,
            "extraction_method": self.extraction_method,
            "warnings": list(self.warnings),
            "evidence": [item.to_dict() for item in selected],
        }


@dataclass(frozen=True)
class CylindricalFeature:
    diameter_mm: float
    length_mm: float
    axis: tuple[float, float, float]
    candidate_count: int = 1
    detection_method: str = "cylindrical_surface"

    def to_dict(self) -> dict[str, Any]:
        return {
            "diameter_mm": self.diameter_mm,
            "length_mm": self.length_mm,
            "axis": list(self.axis),
            "candidate_count": self.candidate_count,
            "detection_method": self.detection_method,
            "classification": "cylindrical candidate; verify whether this is a hole or an external feature",
        }


@dataclass(frozen=True)
class CADDocument:
    source_file: str
    units: str
    bounding_box_mm: tuple[float, float, float]
    volume_mm3: float | None
    surface_area_mm2: float
    center_of_mass_mm: tuple[float, float, float] | None
    solid_count: int
    shell_count: int
    face_count: int
    edge_count: int
    model_valid: bool
    cylindrical_features: tuple[CylindricalFeature, ...]
    warnings: tuple[str, ...]
    vertices: tuple[tuple[float, float, float], ...] = ()
    triangles: tuple[tuple[int, int, int], ...] = ()
    rendered_views: tuple[tuple[str, bytes], ...] = ()

    @property
    def triangle_count(self) -> int:
        return len(self.triangles)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "units": self.units,
            "measurement_method": "OpenCascade geometry kernel",
            "bounding_box_mm": {
                "x": self.bounding_box_mm[0],
                "y": self.bounding_box_mm[1],
                "z": self.bounding_box_mm[2],
            },
            "volume_mm3": self.volume_mm3,
            "surface_area_mm2": self.surface_area_mm2,
            "center_of_mass_mm": list(self.center_of_mass_mm) if self.center_of_mass_mm else None,
            "solid_count": self.solid_count,
            "shell_count": self.shell_count,
            "face_count": self.face_count,
            "edge_count": self.edge_count,
            "triangle_count": self.triangle_count,
            "model_valid": self.model_valid,
            "cylindrical_features": [item.to_dict() for item in self.cylindrical_features],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AuditEvidence:
    source_type: str
    source_file: str
    location: str
    field: str
    value: Any

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuditFinding:
    check: str
    status: str
    summary: str
    evidence: tuple[AuditEvidence, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "status": self.status,
            "summary": self.summary,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class AuditReport:
    part_number: str
    status: str
    findings: tuple[AuditFinding, ...]
    missing_sources: tuple[str, ...] = ()

    @property
    def conflict_count(self) -> int:
        return sum(item.status == "conflict" for item in self.findings)

    @property
    def missing_count(self) -> int:
        if self.missing_sources:
            return len(self.missing_sources)
        return sum(item.status == "missing" for item in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "part_number": self.part_number,
            "status": self.status,
            "conflict_count": self.conflict_count,
            "missing_count": self.missing_count,
            "missing_sources": list(self.missing_sources),
            "findings": [item.to_dict() for item in self.findings],
        }

