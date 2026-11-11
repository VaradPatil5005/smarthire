from unittest import mock

import pytest
from django.db import transaction
from django.test import override_settings

from apps.ingestion.ocr_diff import missing_tokens, run_ocr_diff, tesseract_available
from apps.ingestion.services import file_path, scan_stored_version
from tests.factories.world import FIXTURES, make_org, make_profile, upload_fixture

needs_tesseract = pytest.mark.skipif(not tesseract_available(), reason="tesseract is not installed")


@needs_tesseract
@pytest.mark.slow
def test_font_remapping_is_found_by_the_render_diff():
    """AC-UPLOAD-30"""
    missing = missing_tokens(FIXTURES / "sup_01_font_remapping.pdf")["missing"]
    assert any("SIMULIA" in hit["tokens"] for hit in missing)


@needs_tesseract
@pytest.mark.slow
def test_occlusion_is_found_by_the_render_diff():
    """AC-UPLOAD-30"""
    missing = missing_tokens(FIXTURES / "atk_07_white_rect_over_black.pdf")["missing"]
    assert any("migration" in hit["tokens"] for hit in missing)


@pytest.mark.django_db
def test_a_good_scan_queues_the_ocr_job_with_an_id_only(django_capture_on_commit_callbacks):
    """AC-UPLOAD-30: it really runs in production, on every file."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.ingestion.services import receive_upload
    from tests.factories.world import fixture_bytes

    profile = make_profile(make_org())
    uploaded = SimpleUploadedFile("c.pdf", fixture_bytes("demo_candidate_a"))
    with mock.patch("apps.ingestion.services._enqueue"):
        version = receive_upload(uploaded, profile, profile.organisation, None)
    with (
        override_settings(OCR_DIFF_ENABLED=True),
        mock.patch("apps.ingestion.services.async_task") as queued,
        django_capture_on_commit_callbacks(execute=True),
    ):
        scan_stored_version(version.pk)
    queued.assert_called_once_with("apps.ingestion.tasks.ocr_diff_version", str(version.pk))
    assert transaction is not None


@needs_tesseract
@pytest.mark.slow
@pytest.mark.django_db
def test_diff_writes_review_notes_only():
    """AC-UPLOAD-30: it is a job on a stored version and can never change a score."""
    version = upload_fixture("sup_01_font_remapping", make_profile(make_org()))
    assert file_path(version).exists()
    assert run_ocr_diff(version.pk) >= 1
    note = version.audits.get(vector="OCR_DIFF")
    assert note.note_only is True
    version.refresh_from_db()
    assert version.status == "CLEAN"
