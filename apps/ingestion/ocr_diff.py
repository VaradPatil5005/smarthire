"""Render-and-OCR diff (T4.6): text in the file but absent from what a reader would see.

This catches font remapping (vector 13), which the fast scan cannot. It needs the tesseract program,
is much slower, and runs as its own background job in the scanner's child process. OCR misreads
tables and non-Latin scripts, so a hit is only a note for a reviewer: it never excludes text or
changes a score. It is on when OCR_DIFF_ENABLED is set and tesseract is installed.
"""

import logging
import shutil

from django.conf import settings

from .models import HiddenSpanAudit, ResumeVersion
from .services import file_path, run_in_child

logger = logging.getLogger(__name__)


def tesseract_path():
    return shutil.which("tesseract")


def tesseract_available() -> bool:
    return tesseract_path() is not None


def missing_tokens(path):
    return run_in_child(["ocr", str(path), tesseract_path()], settings.SCAN_TIME_LIMIT_SECONDS)


def run_ocr_diff(version_id) -> int:
    """Record what OCR could not find. Returns the number of notes written."""
    if not tesseract_available():
        logger.info("ocr diff skipped version=%s reason=no-tesseract", version_id)
        return 0
    version = ResumeVersion.objects.get(pk=version_id)
    if not version.is_servable:
        return 0
    result = missing_tokens(file_path(version))
    if "failure" in result:
        logger.info("ocr diff failed version=%s", version.pk)
        return 0
    notes = 0
    for hit in result["missing"]:
        text = " ".join(hit["tokens"])
        HiddenSpanAudit.objects.create(
            organisation_id=version.organisation_id,
            resume_version=version,
            page=hit["page"],
            vector="OCR_DIFF",
            text=text[: settings.AUDIT_TEXT_MAX_CHARS],
            true_length=len(text),
            note_only=True,
        )
        notes += 1
    logger.info("ocr diff done version=%s notes=%s", version.pk, notes)
    return notes
