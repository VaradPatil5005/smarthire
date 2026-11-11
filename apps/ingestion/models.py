"""Uploaded résumés. Files and everything extracted from them are untrusted data."""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.tenancy.models import TenantModel


class ResumeStatus(models.TextChoices):
    QUARANTINED = "QUARANTINED", "Quarantined"
    CLEAN = "CLEAN", "Clean"
    FLAGGED = "FLAGGED", "Flagged"
    FAILED = "FAILED", "Failed"


class FailureCode(models.TextChoices):
    NONE = "", "None"
    ENCRYPTED = "ENCRYPTED", "Encrypted"
    CORRUPT = "CORRUPT", "Corrupt"
    TOO_MANY_PAGES = "TOO_MANY_PAGES", "Too many pages"
    PAGE_TOO_LARGE = "PAGE_TOO_LARGE", "Page too large"
    TOO_MUCH_DATA = "TOO_MUCH_DATA", "Too much compressed data"
    TIMEOUT = "TIMEOUT", "Timed out"
    PARSER_ERROR = "PARSER_ERROR", "Parser error"
    STUCK = "STUCK", "Processing stopped"


RECOVERY_MESSAGES = {
    FailureCode.ENCRYPTED: "This PDF is password-protected. Remove the password and upload it "
    "again, or add your skills with the form.",
    FailureCode.CORRUPT: "This PDF could not be read. Export it again and upload the new file, or "
    "add your skills with the form.",
    FailureCode.TOO_MANY_PAGES: "This PDF has too many pages. Upload a résumé of at most 10 pages, "
    "or add your skills with the form.",
    FailureCode.PAGE_TOO_LARGE: "A page in this PDF is unusually large. Export it at a normal page "
    "size, or add your skills with the form.",
    FailureCode.TOO_MUCH_DATA: "This PDF holds too much data to process. Export a smaller copy, or "
    "add your skills with the form.",
    FailureCode.TIMEOUT: "Processing this PDF took too long. Try a simpler export, or add your "
    "skills with the form.",
    FailureCode.PARSER_ERROR: "We could not process this PDF. Try exporting it again, or add your "
    "skills with the form.",
    FailureCode.STUCK: "Processing stopped before it finished. Upload the file again, or add your "
    "skills with the form.",
}


class ResumeVersion(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        "talent.TalentProfile", on_delete=models.CASCADE, related_name="resumes"
    )
    version = models.PositiveIntegerField()
    object_key = models.CharField(max_length=200, unique=True)
    sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveIntegerField()
    status = models.CharField(
        max_length=12, choices=ResumeStatus.choices, default=ResumeStatus.QUARANTINED
    )
    failure_code = models.CharField(
        max_length=16, choices=FailureCode.choices, blank=True, default=""
    )
    pages = models.PositiveSmallIntegerField(null=True, blank=True)
    # Only ever filled from the scanner's visible output.
    visible_text = models.TextField(blank=True)
    visible_spans = models.JSONField(default=list, blank=True)
    page_sizes = models.JSONField(default=list, blank=True)
    scanned_pages = models.JSONField(default=list, blank=True)
    strip_counts = models.JSONField(default=dict, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    scanned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["profile_id", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["profile", "version"], name="unique_resume_version")
        ]

    def __str__(self) -> str:
        return f"resume version {self.pk}"

    @property
    def is_servable(self) -> bool:
        return self.status in (ResumeStatus.CLEAN, ResumeStatus.FLAGGED)

    @property
    def recovery_message(self) -> str:
        return RECOVERY_MESSAGES.get(self.failure_code, "")

    @property
    def is_fully_scanned(self) -> bool:
        return bool(self.pages) and len(self.scanned_pages) == self.pages

    def visible_text_or_none(self):
        """The one way to read résumé text. Quarantined and failed files yield nothing."""
        return self.visible_text if self.is_servable else None


class Disposition(models.TextChoices):
    PENDING = "PENDING", "Pending"
    CONFIRMED = "CONFIRMED", "Confirmed"
    DISMISSED = "DISMISSED", "Dismissed"


class HiddenSpanAudit(TenantModel):
    """Reviewer-only record of excluded text. It has zero weight and is never evidence."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resume_version = models.ForeignKey(
        ResumeVersion, on_delete=models.CASCADE, related_name="audits"
    )
    page = models.PositiveSmallIntegerField(null=True, blank=True)
    bbox = models.JSONField(null=True, blank=True)
    vector = models.CharField(max_length=32)
    field_name = models.CharField(max_length=64, blank=True)
    text = models.TextField(blank=True)
    true_length = models.PositiveIntegerField(default=0)
    note_only = models.BooleanField(default=False)
    disposition = models.CharField(
        max_length=10, choices=Disposition.choices, default=Disposition.PENDING
    )

    class Meta:
        ordering = ["page", "id"]

    def __str__(self) -> str:
        return f"audit {self.pk}"
