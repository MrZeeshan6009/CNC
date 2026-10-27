from pathlib import Path

import pytest

from src.cad_reader import CADReadError, extract_cad


SAMPLE = Path("data/sample/2280_model.igs")


def test_extracts_verified_geometry_and_views() -> None:
    document = extract_cad(SAMPLE.read_bytes(), SAMPLE.name)
    assert document.bounding_box_mm == pytest.approx((120.0, 75.0, 10.0), abs=0.01)
    assert document.volume_mm3 == pytest.approx(86858.4073, rel=1e-4)
    assert document.surface_area_mm2 > 0
    assert document.solid_count == 1
    assert document.model_valid
    assert document.triangle_count > 0
    assert {name for name, _ in document.rendered_views} == {
        "Front",
        "Back",
        "Left",
        "Right",
        "Top",
        "Bottom",
        "Isometric",
    }


def test_detects_four_diameter_ten_cylindrical_candidates() -> None:
    document = extract_cad(SAMPLE.read_bytes(), SAMPLE.name)
    feature = next(item for item in document.cylindrical_features if item.diameter_mm == 10.0)
    assert feature.candidate_count == 4
    assert feature.length_mm == pytest.approx(10.0, abs=0.01)


def test_invalid_iges_is_rejected() -> None:
    with pytest.raises(CADReadError):
        extract_cad(b"not an iges model", "broken.igs")


def test_wrong_extension_is_rejected() -> None:
    with pytest.raises(CADReadError, match="Only .igs"):
        extract_cad(SAMPLE.read_bytes(), "model.step")
