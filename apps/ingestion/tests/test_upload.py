import hashlib
import logging
import os
import subprocess
from datetime import timedelta
from unittest import mock

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.utils import timezone

from apps.ingestion import services
from apps.ingestion.models import FailureCode, ResumeVersion
from apps.ingestion.services import (
    UploadRefused,
    file_path,
    receive_upload,
    run_scanner,
    scan_stored_version,
)
from apps.matching.vocabulary import load_seed_pack
from apps.tenancy.models import Membership, Role
from tests.factories.world import (
    client_for,
    fixture_bytes,
    make_org,
    make_profile,
    make_user,
    upload_fixture,
)

pytestmark = pytest.mark.django_db
URL = "/api/profiles/me/resumes/"


@pytest.fixture(autouse=True)
def vocabulary():
    load_seed_pack()


@pytest.fixture
def org():
    return make_org()


@pytest.fixture
def candidate(org):
    return make_user(org, Role.CANDIDATE)


@pytest.fixture
def profile(org, candidate):
    return make_profile(org, owner=candidate)


def _file(data=None, name="resume.pdf", content_type="application/pdf"):
    data = fixture_bytes("demo_candidate_a") if data is None else data
    return SimpleUploadedFile(name, data, content_type=content_type)


def _post(client, data=None, **kwargs):
    return client.post(URL, {"file": _file(data, **kwargs)})


def test_valid_upload_returns_202_quarantined_and_parses_nothing_in_the_request(candidate, profile):
    """AC-UPLOAD-01"""
    client = client_for(candidate)
    with (
        mock.patch("pymupdf.open", side_effect=AssertionError("parser ran in the request")),
        mock.patch("apps.ingestion.services._enqueue") as enqueue,
        mock.patch("django.db.transaction.on_commit", side_effect=lambda function: function()),
    ):
        response = _post(client)
    assert response.status_code == 202
    version = ResumeVersion.objects.get()
    assert version.status == "QUARANTINED"
    assert response.json()["id"] == str(version.pk)
    enqueue.assert_called_once_with(version.pk)


@pytest.mark.parametrize(
    ("fixture", "kwargs"),
    [("upl_docx_renamed", {}), ("upl_text_renamed", {})],
)
def test_non_pdf_is_refused_with_a_recovery_message_and_nothing_stored(
    candidate, profile, fixture, kwargs
):
    """AC-UPLOAD-02"""
    response = _post(client_for(candidate), fixture_bytes(fixture), **kwargs)
    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]
    assert not ResumeVersion.objects.exists()


def test_declared_mime_is_ignored_for_a_real_pdf(candidate, profile):
    """AC-UPLOAD-02"""
    response = _post(client_for(candidate), content_type="text/plain")
    assert response.status_code == 202


def test_polyglot_with_pdf_header_fails_parsing_and_is_never_served(candidate, profile):
    """AC-UPLOAD-02"""
    client = client_for(candidate)
    response = _post(client, b"%PDF-1.7\n<html><script>alert(1)</script></html>")
    assert response.status_code == 202
    version = ResumeVersion.objects.get()
    scan_stored_version(version.pk)
    version.refresh_from_db()
    assert version.status == "FAILED"
    assert client.get(f"/api/resumes/{version.pk}/download/").status_code == 404


def test_size_limit_is_exact(candidate, profile):
    """AC-UPLOAD-03"""
    client = client_for(candidate)
    limit = settings.UPLOAD_MAX_BYTES
    assert limit == 5_242_880
    assert _post(client, b"%PDF-" + b"0" * (limit - 5)).status_code == 202
    refused = _post(client, b"%PDF-" + b"0" * (limit - 4))
    assert refused.status_code == 400
    assert "5 MB" in refused.json()["detail"]


@pytest.mark.parametrize(
    ("fixture", "status", "code"),
    [
        ("upl_10_pages", "CLEAN", ""),
        ("upl_11_pages", "FAILED", FailureCode.TOO_MANY_PAGES),
        ("upl_200_pages", "FAILED", FailureCode.TOO_MANY_PAGES),
        ("upl_page_too_large", "FAILED", FailureCode.PAGE_TOO_LARGE),
        ("sup_15_flate_bomb", "FAILED", FailureCode.TOO_MUCH_DATA),
    ],
)
def test_page_and_data_limits_run_in_the_job(profile, candidate, fixture, status, code):
    """AC-UPLOAD-04"""
    version = upload_fixture(fixture, profile, candidate)
    assert version.status == status
    assert version.failure_code == code
    if status == "FAILED":
        assert version.recovery_message
        assert version.visible_text == ""


@pytest.mark.parametrize(
    ("fixture", "code"),
    [("upl_encrypted", FailureCode.ENCRYPTED), ("upl_corrupt", FailureCode.CORRUPT)],
)
def test_encrypted_and_corrupt_fail_with_their_own_message(candidate, profile, fixture, code):
    """AC-UPLOAD-05"""
    assert _post(client_for(candidate), fixture_bytes(fixture)).status_code == 202
    version = ResumeVersion.objects.get()
    scan_stored_version(version.pk)
    version.refresh_from_db()
    assert (version.status, version.failure_code) == ("FAILED", code)
    assert version.recovery_message


def test_zip_bomb_is_refused_by_magic_bytes_and_others_still_upload(org, candidate, profile):
    """AC-UPLOAD-06"""
    other = make_user(org, Role.CANDIDATE)
    make_profile(org, owner=other)
    zip_bytes = b"PK\x03\x04" + b"\0" * 1024
    with mock.patch("zipfile.ZipFile", side_effect=AssertionError("opened an archive")):
        assert _post(client_for(candidate), zip_bytes).status_code == 400
    assert _post(client_for(other)).status_code == 202


@pytest.mark.parametrize(
    "name", ["../../evil.pdf", "a<script>alert(1)</script>.pdf", "x\r\nSet-Cookie: a=b.pdf"]
)
def test_client_filename_plays_no_part(candidate, profile, name):
    """AC-UPLOAD-07"""
    client = client_for(candidate)
    assert _post(client, name=name.replace("\r\n", "-")).status_code == 202
    version = ResumeVersion.objects.get()
    assert version.object_key == f"{version.organisation_id}/{version.pk}.pdf"
    root = os.path.realpath(settings.PRIVATE_MEDIA_ROOT)
    assert os.path.realpath(file_path(version)).startswith(root)
    version.status = "CLEAN"
    version.save()
    served = client.get(f"/api/resumes/{version.pk}/download/")
    assert served["Content-Disposition"] == 'attachment; filename="resume-v1.pdf"'


def test_storage_is_outside_served_paths():
    """AC-UPLOAD-07"""
    root = str(settings.PRIVATE_MEDIA_ROOT)
    assert not root.startswith(str(settings.STATIC_ROOT))
    assert "static" not in os.path.basename(root)


def _served(response):
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Disposition"].startswith("attachment")
    assert b"".join(response.streaming_content).startswith(b"%PDF-")


def test_serving_matrix_all_nine_cases(org, candidate, profile):
    """AC-UPLOAD-08"""
    clean = upload_fixture("demo_candidate_a", profile, candidate)
    flagged = upload_fixture("atk_01_white_on_white_keywords", profile, candidate)
    quarantined = ResumeVersion.objects.create(
        organisation=org,
        profile=profile,
        version=9,
        object_key=f"{org.pk}/q.pdf",
        sha256="0" * 64,
        size_bytes=1,
    )
    failed = upload_fixture("upl_corrupt", profile, candidate)
    owner = client_for(candidate)
    recruiter = client_for(make_user(org, Role.RECRUITER))
    url = "/api/resumes/{}/download/"
    for version in (clean, flagged):
        _served(owner.get(url.format(version.pk)))
        _served(recruiter.get(url.format(version.pk)))
    peer = client_for(make_user(org, Role.CANDIDATE))
    assert peer.get(url.format(clean.pk)).status_code == 404
    other_org = client_for(make_user(make_org()))
    assert other_org.get(url.format(clean.pk)).status_code == 404
    revoked_user = make_user(org, Role.RECRUITER)
    revoked = client_for(revoked_user)
    Membership.objects.filter(user=revoked_user).update(revoked_at=timezone.now())
    assert revoked.get(url.format(clean.pk)).status_code == 403
    assert Client().get(url.format(clean.pk)).status_code in (401, 403)
    assert owner.get(url.format(quarantined.pk)).status_code == 404
    assert recruiter.get(url.format(quarantined.pk)).status_code == 404
    assert recruiter.get(url.format(failed.pk)).status_code == 404
    assert Client().get(f"/private_media/{clean.object_key}").status_code in (302, 404)


@override_settings(UPLOAD_RATE_LIMIT_PER_HOUR=2)
def test_rate_limit_refuses_and_keeps_earlier_versions_and_others_unaffected(
    org, candidate, profile
):
    """AC-UPLOAD-09"""
    client = client_for(candidate)
    assert _post(client).status_code == 202
    assert _post(client).status_code == 202
    refused = _post(client)
    assert refused.status_code == 400
    assert "too many" in refused.json()["detail"]
    assert ResumeVersion.objects.count() == 2
    other = make_user(org, Role.CANDIDATE)
    make_profile(org, owner=other)
    assert _post(client_for(other)).status_code == 202


@override_settings(UPLOAD_STORAGE_CAP_BYTES=10)
def test_storage_cap_refuses(candidate, profile):
    """AC-UPLOAD-09"""
    response = _post(client_for(candidate))
    assert response.status_code == 400
    assert "storage limit" in response.json()["detail"]


def test_replacement_creates_a_new_version_and_keeps_the_old(candidate, profile):
    """AC-CAND-07"""
    first = upload_fixture("demo_candidate_a", profile, candidate)
    second = upload_fixture("demo_candidate_b", profile, candidate)
    assert (first.version, second.version) == (1, 2)
    assert file_path(first).exists()
    assert hashlib.sha256(file_path(first).read_bytes()).hexdigest() == first.sha256


def test_failed_upload_leaves_last_good_version_and_profile(candidate, profile):
    """AC-CAND-08"""
    good = upload_fixture("demo_candidate_a", profile, candidate)
    title = profile.title
    upload_fixture("upl_corrupt", profile, candidate)
    good.refresh_from_db()
    profile.refresh_from_db()
    assert good.status == "CLEAN"
    assert profile.title == title
    assert profile.spans.filter(resume_version=good).exists()


def test_parser_exception_fails_at_once(candidate, profile):
    """AC-UPLOAD-10"""
    with mock.patch(
        "apps.ingestion.services.subprocess.run",
        return_value=subprocess.CompletedProcess([], 1, b"", b"crash"),
    ):
        version = upload_fixture("demo_candidate_a", profile, candidate)
    assert (version.status, version.failure_code) == ("FAILED", FailureCode.PARSER_ERROR)
    assert version.visible_text == ""


def test_timeout_fails_and_the_limit_is_below_the_cluster_timeout(candidate, profile):
    """AC-UPLOAD-10"""
    from config.settings import base

    assert base.Q_CLUSTER["timeout"] > base.SCAN_TIME_LIMIT_SECONDS
    with mock.patch(
        "apps.ingestion.services.subprocess.run",
        side_effect=subprocess.TimeoutExpired("scan", 1),
    ):
        version = upload_fixture("demo_candidate_a", profile, candidate)
    assert version.failure_code == FailureCode.TIMEOUT


def test_killed_worker_is_swept_to_failed_without_retry(org, candidate, profile):
    """AC-UPLOAD-10"""
    from config.settings import base

    assert base.Q_CLUSTER["max_attempts"] == 1
    version = receive_upload(_file(), profile, org, candidate)
    assert services.sweep_stuck_versions() == 0
    later = timezone.now() + timedelta(seconds=settings.SCAN_STUCK_AFTER_SECONDS + 1)
    assert services.sweep_stuck_versions(now=later) == 1
    version.refresh_from_db()
    assert (version.status, version.failure_code) == ("FAILED", FailureCode.STUCK)


def test_duplicate_job_delivery_gives_one_result(candidate, profile):
    """AC-UPLOAD-10"""
    version = upload_fixture("atk_01_white_on_white_keywords", profile, candidate)
    audits = version.audits.count()
    spans = profile.spans.count()
    scan_stored_version(version.pk)
    assert version.audits.count() == audits
    assert profile.spans.count() == spans


def test_child_process_has_no_secrets_or_database_url(monkeypatch):
    """AC-UPLOAD-11"""
    monkeypatch.setenv("DATABASE_URL", "postgres://secret")
    monkeypatch.setenv("DJANGO_SECRET_KEY", "secret")
    env = services._child_environment()
    assert "DATABASE_URL" not in env
    assert "DJANGO_SECRET_KEY" not in env
    assert "DJANGO_SETTINGS_MODULE" not in env


def test_worker_module_imports_no_django():
    """AC-UPLOAD-11"""
    from pathlib import Path

    for name in ("worker.py", "scanner.py"):
        source = (Path(settings.BASE_DIR) / "apps" / "ingestion" / name).read_text(encoding="utf-8")
        assert "import django" not in source
        assert "from django" not in source


@pytest.mark.parametrize("status", ["QUARANTINED", "FAILED"])
def test_unscanned_or_failed_versions_yield_no_text(org, profile, status):
    """AC-UPLOAD-12"""
    version = ResumeVersion.objects.create(
        organisation=org,
        profile=profile,
        version=1,
        object_key=f"{org.pk}/x.pdf",
        sha256="0" * 64,
        size_bytes=1,
        status=status,
        visible_text="should never be read",
    )
    assert version.visible_text_or_none() is None


MARKER = "ZZMARKERZZ"


def test_logs_and_task_arguments_hold_ids_only(candidate, profile, caplog):
    """AC-UPLOAD-32"""
    caplog.set_level(logging.DEBUG)
    with mock.patch("apps.ingestion.services.async_task") as queued:
        version = receive_upload(_file(), profile, profile.organisation, candidate)
        services._enqueue(version.pk)
    assert queued.call_args.args == ("apps.ingestion.tasks.scan_version", str(version.pk))
    scan_stored_version(version.pk)
    upload_fixture("sup_02_hidden_instruction", profile, candidate)
    for record in caplog.records:
        message = record.getMessage().lower()
        assert "ignore previous" not in message
        assert "enovia" not in message
        assert "%pdf" not in message


def test_scanner_result_function_runs_in_a_child_process(profile):
    """AC-UPLOAD-11"""
    from tests.factories.world import FIXTURES

    result = run_scanner(FIXTURES / "demo_candidate_a.pdf")
    assert result["status"] == "CLEAN"


def test_unknown_upload_without_file_is_refused(candidate, profile):
    """AC-UPLOAD-02"""
    with pytest.raises(UploadRefused):
        receive_upload(None, profile, profile.organisation, candidate)
