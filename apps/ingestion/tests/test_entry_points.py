"""The worker and task entry points, run in-process so that coverage can see them."""

import json
from unittest import mock

import pytest
from django.core.management import call_command

from apps.ingestion import ocr_diff, tasks, worker
from apps.ingestion.models import ResumeVersion
from tests.factories.world import FIXTURES, make_org, make_profile, upload_fixture

LIMITS = json.dumps(
    {
        "max_pages": 10,
        "max_page_points": 3370,
        "max_decompressed_bytes": 10**8,
        "min_contrast": 1.5,
        "audit_text_max_chars": 4000,
    }
)


def test_worker_prints_a_scan_result_as_json(capsys):
    """AC-UPLOAD-11"""
    assert worker.main([str(FIXTURES / "demo_candidate_a.pdf"), "", LIMITS]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "CLEAN"


def test_worker_reports_a_failure_code(capsys):
    """AC-UPLOAD-05"""
    assert worker.main([str(FIXTURES / "upl_corrupt.pdf"), "", LIMITS]) == 0
    assert json.loads(capsys.readouterr().out) == {"failure": "CORRUPT"}


@pytest.mark.skipif(not ocr_diff.tesseract_available(), reason="tesseract is not installed")
@pytest.mark.slow
def test_worker_runs_the_ocr_mode(capsys):
    """AC-UPLOAD-30"""
    path = str(FIXTURES / "sup_01_font_remapping.pdf")
    assert worker.main(["ocr", path, ocr_diff.tesseract_path()]) == 0
    assert "missing" in json.loads(capsys.readouterr().out)


@pytest.mark.django_db
def test_scan_task_and_sweep_command_and_sweep_task():
    """AC-UPLOAD-10"""
    version = upload_fixture("demo_candidate_a", make_profile(make_org()))
    tasks.scan_version(str(version.pk))
    tasks.sweep_stuck()
    call_command("sweep_stuck_scans", verbosity=0)
    assert ResumeVersion.objects.get(pk=version.pk).status == "CLEAN"


@pytest.mark.django_db
def test_ocr_task_skips_cleanly_without_tesseract():
    """AC-UPLOAD-30"""
    version = upload_fixture("demo_candidate_a", make_profile(make_org()))
    with mock.patch("apps.ingestion.ocr_diff.tesseract_path", return_value=None):
        tasks.ocr_diff_version(str(version.pk))
    assert not version.audits.filter(vector="OCR_DIFF").exists()


@pytest.mark.django_db
def test_ocr_failure_writes_no_note():
    """AC-UPLOAD-30"""
    version = upload_fixture("demo_candidate_a", make_profile(make_org()))
    with (
        mock.patch("apps.ingestion.ocr_diff.tesseract_path", return_value="tesseract"),
        mock.patch("apps.ingestion.ocr_diff.missing_tokens", return_value={"failure": "TIMEOUT"}),
    ):
        assert ocr_diff.run_ocr_diff(version.pk) == 0


@pytest.mark.django_db
def test_ocr_skips_a_failed_version():
    """AC-UPLOAD-12"""
    version = upload_fixture("upl_corrupt", make_profile(make_org()))
    with mock.patch("apps.ingestion.ocr_diff.tesseract_path", return_value="tesseract"):
        assert ocr_diff.run_ocr_diff(version.pk) == 0
