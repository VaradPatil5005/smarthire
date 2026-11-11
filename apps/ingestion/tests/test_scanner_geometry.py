"""Synthetic rendering regressions: eligibility follows the page the reviewer sees."""

import pymupdf
import pytest

from apps.ingestion.scanner import Limits, scan_pdf

LIMITS = Limits(10, 3370, 100 * 1024 * 1024, 1.5, 4000)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotated_visible_text_stays_eligible_and_boxes_follow_the_preview(tmp_path, rotation):
    path = tmp_path / "rotated.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=420, height=595)
        # Below the rotated page's shorter dimension, but inside the unrotated page.
        page.insert_text((72, 520), "Python Django ENOVIA", fontsize=12)
        original_box = pymupdf.Rect(page.get_texttrace()[0]["bbox"])
        page.set_rotation(rotation)
        expected_box = original_box * page.rotation_matrix
        doc.save(path)

    result = scan_pdf(path, LIMITS, preview_dir=tmp_path)

    assert result["visible_text"] == "Python Django ENOVIA"
    assert result["status"] == "CLEAN"
    assert result["audits"] == []
    assert result["visible_spans"][0]["bbox"] == pytest.approx(list(expected_box))
    assert (tmp_path / "page-1.png").exists()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_hidden_text_stays_excluded_on_rotated_pages(tmp_path, rotation):
    path = tmp_path / "rotated-hidden.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=420, height=595)
        page.insert_text((72, 72), "Python", fontsize=12)
        page.insert_text((72, 96), "ENOVIA", fontsize=12, color=(1, 1, 1))
        hidden_box = pymupdf.Rect(page.get_texttrace()[1]["bbox"])
        page.set_rotation(rotation)
        expected_box = hidden_box * page.rotation_matrix
        doc.save(path)

    result = scan_pdf(path, LIMITS)

    assert result["visible_text"] == "Python"
    assert result["status"] == "FLAGGED"
    audit = next(a for a in result["audits"] if a["text"] == "ENOVIA")
    assert audit["vector"] == "LOW_CONTRAST"
    assert audit["bbox"] == pytest.approx(list(expected_box))


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotated_scanned_page_is_routed_to_manual_entry_without_an_attack_flag(tmp_path, rotation):
    path = tmp_path / "scan.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=800, height=200)
        image = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 800, 200), False)
        image.clear_with(255)
        page.insert_image(page.rect, stream=image.tobytes("png"))
        page.insert_text((72, 72), "Python", render_mode=3)
        page.set_rotation(rotation)
        doc.save(path)

    result = scan_pdf(path, LIMITS)

    assert result["status"] == "CLEAN"
    assert result["scanned_pages"] == [1]
    assert result["visible_text"] == ""
    assert result["audits"] == []


@pytest.mark.parametrize("opacity", [0, 0.1, 1])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_only_opaque_rectangles_exclude_the_text_they_cover(tmp_path, opacity, rotation):
    path = tmp_path / "overlay.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), "Python Django", fontsize=12)
        page.draw_rect(
            pymupdf.Rect(70, 56, 160, 77),
            fill=(1, 1, 1),
            fill_opacity=opacity,
            color=None,
        )
        page.set_rotation(rotation)
        doc.save(path)

    result = scan_pdf(path, LIMITS)

    if opacity == 1:
        assert result["visible_text"] == ""
        assert result["status"] == "FLAGGED"
    else:
        assert result["visible_text"] == "Python Django"
        assert result["status"] == "CLEAN"
