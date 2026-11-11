"""Receiving and scanning uploads. No PDF parser ever runs in the web process."""

import hashlib
import json
import logging
import os
import shutil
import subprocess  # nosec B404
import sys
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django_q.tasks import async_task

from apps.matching.extractor import extract_for_version
from apps.matching.vocabulary import latest_dictionary

from .models import FailureCode, HiddenSpanAudit, ResumeStatus, ResumeVersion

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"


class UploadRefused(Exception):
    """Refused in the request, with a message the candidate can act on."""


def _object_path(key) -> Path:
    root = Path(settings.PRIVATE_MEDIA_ROOT).resolve()
    path = (root / key).resolve()
    if root not in path.parents:
        raise ValueError("Object key escapes private storage")
    return path


def file_path(version) -> Path:
    return _object_path(version.object_key)


def preview_path(version, page) -> Path:
    return _object_path(f"{version.organisation_id}/{version.pk}/page-{int(page)}.png")


def _read_upload(uploaded):
    if uploaded is None:
        raise UploadRefused("Choose a PDF file to upload.")
    if uploaded.size > settings.UPLOAD_MAX_BYTES:
        raise UploadRefused("This file is over the 5 MB limit. Export a smaller PDF and try again.")
    data = b"".join(uploaded.chunks())
    if not data.startswith(PDF_MAGIC):
        raise UploadRefused(
            "Only PDF résumés are accepted. Export your résumé as a PDF, or add your skills with "
            "the form."
        )
    return data


def _check_quota(profile, organisation, user, size):
    hour_ago = timezone.now() - timedelta(hours=1)
    recent = ResumeVersion.objects.for_org(organisation).filter(
        uploaded_by=user, created_at__gte=hour_ago
    )
    if recent.count() >= settings.UPLOAD_RATE_LIMIT_PER_HOUR:
        raise UploadRefused("You have uploaded too many files this hour. Please try again later.")
    used = profile.resumes.aggregate(total=Sum("size_bytes"))["total"] or 0
    if used + size > settings.UPLOAD_STORAGE_CAP_BYTES:
        raise UploadRefused(
            "This profile has reached its storage limit. Contact your recruiter to remove old "
            "files, or add your skills with the form."
        )


def receive_upload(uploaded, profile, organisation, user) -> ResumeVersion:
    """Validate in the request, store privately, quarantine, and queue the scan."""
    data = _read_upload(uploaded)
    _check_quota(profile, organisation, user, len(data))
    version_id = uuid.uuid4()
    key = f"{organisation.pk}/{version_id}.pdf"
    path = _object_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    with transaction.atomic():
        latest = profile.resumes.select_for_update().order_by("-version").first()
        version = ResumeVersion.objects.create(
            id=version_id,
            organisation=organisation,
            profile=profile,
            version=(latest.version + 1) if latest else 1,
            object_key=key,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            uploaded_by=user,
        )
    logger.info("upload received version=%s profile=%s", version.pk, profile.pk)
    transaction.on_commit(lambda: _enqueue(version.pk))
    return version


def _enqueue(version_id):
    # IDs only: the task record never holds résumé text or contact fields.
    async_task("apps.ingestion.tasks.scan_version", str(version_id))


def _enqueue_ocr(version_id):
    async_task("apps.ingestion.tasks.ocr_diff_version", str(version_id))


def _limits_json():
    return json.dumps(
        {
            "max_pages": settings.UPLOAD_MAX_PAGES,
            "max_page_points": settings.UPLOAD_MAX_PAGE_POINTS,
            "max_decompressed_bytes": settings.UPLOAD_MAX_DECOMPRESSED_BYTES,
            "min_contrast": settings.SCAN_MIN_CONTRAST_RATIO,
            "audit_text_max_chars": settings.AUDIT_TEXT_MAX_CHARS,
        }
    )


def _child_environment():
    """Only what Python needs to start. No secrets, no database URL, no Django settings."""
    env = {"PYTHONPATH": str(settings.BASE_DIR), "PYTHONIOENCODING": "utf-8"}
    for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR"):
        if name in os.environ:
            env[name] = os.environ[name]
    return env


def run_scanner(path, preview_dir=""):
    """Run the scanner in a child process under the time limit. Returns its JSON result."""
    return run_in_child([str(path), str(preview_dir), _limits_json()])


def run_in_child(arguments, timeout=None):
    """Run the worker with a scrubbed environment and a time limit. Returns its JSON output."""
    command = [sys.executable, "-m", "apps.ingestion.worker", *arguments]
    try:
        completed = subprocess.run(  # noqa: S603  # nosec B603
            command,
            capture_output=True,
            timeout=timeout or settings.SCAN_TIME_LIMIT_SECONDS,
            env=_child_environment(),
            cwd=str(settings.BASE_DIR),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"failure": FailureCode.TIMEOUT}
    if completed.returncode != 0:
        return {"failure": FailureCode.PARSER_ERROR}
    try:
        return json.loads(completed.stdout.decode("utf-8"))
    except ValueError:
        return {"failure": FailureCode.PARSER_ERROR}


def _store_result(version, result):
    version.status = result["status"]
    version.pages = result["pages"]
    version.page_sizes = result["page_sizes"]
    version.visible_text = result["visible_text"]
    version.visible_spans = result["visible_spans"]
    version.scanned_pages = result["scanned_pages"]
    version.strip_counts = result["strip_counts"]
    version.scanned_at = timezone.now()
    version.save()
    HiddenSpanAudit.objects.bulk_create(
        [
            HiddenSpanAudit(
                organisation_id=version.organisation_id, resume_version=version, **audit
            )
            for audit in result["audits"]
        ]
    )


def scan_stored_version(version_id) -> None:
    """The background job. A duplicate delivery of one job gives one result."""
    with transaction.atomic():
        version = ResumeVersion.objects.select_for_update().get(pk=version_id)
        if version.status != ResumeStatus.QUARANTINED:
            return
        preview_dir = tempfile.mkdtemp(prefix="scan-preview-")
        try:
            result = run_scanner(file_path(version), preview_dir)
            if "failure" in result:
                version.status = ResumeStatus.FAILED
                version.failure_code = result["failure"]
                version.scanned_at = timezone.now()
                version.save(update_fields=["status", "failure_code", "scanned_at"])
                logger.info("scan failed version=%s code=%s", version.pk, version.failure_code)
                return
            _store_result(version, result)
            target = preview_path(version, 1).parent
            target.mkdir(parents=True, exist_ok=True)
            for image in Path(preview_dir).glob("page-*.png"):
                shutil.move(str(image), target / image.name)
        finally:
            shutil.rmtree(preview_dir, ignore_errors=True)
        extract_for_version(version, latest_dictionary())
        if settings.OCR_DIFF_ENABLED:
            transaction.on_commit(lambda: _enqueue_ocr(version.pk))
        logger.info(
            "scan done version=%s status=%s strips=%s",
            version.pk,
            version.status,
            sum(version.strip_counts.values()),
        )


def sweep_stuck_versions(now=None) -> int:
    """A killed worker leaves a version quarantined. Old ones move to FAILED, with no retry."""
    cutoff = (now or timezone.now()) - timedelta(seconds=settings.SCAN_STUCK_AFTER_SECONDS)
    return ResumeVersion.objects.filter(
        status=ResumeStatus.QUARANTINED, created_at__lt=cutoff
    ).update(status=ResumeStatus.FAILED, failure_code=FailureCode.STUCK, scanned_at=timezone.now())


def candidate_status(version) -> str:
    """What a candidate sees. Clean and flagged look the same, so nobody can probe the detector."""
    if version.status == ResumeStatus.QUARANTINED:
        return "PENDING"
    if version.status == ResumeStatus.FAILED:
        return "FAILED"
    return "PROCESSED"
