"""Bulk import batches, with row-level review and field-level rollback."""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.tenancy.models import TenantModel


class BatchStatus(models.TextChoices):
    PREVIEW = "PREVIEW", "Preview"
    CONFIRMED = "CONFIRMED", "Confirmed"
    ROLLED_BACK = "ROLLED_BACK", "Rolled back"


class ImportBatch(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_system = models.CharField(max_length=64)
    source_digest = models.CharField(max_length=64)
    mapping_version = models.PositiveIntegerField(default=1)
    mapping = models.JSONField(default=dict)
    # Header row then raw rows, kept only until confirmation so the mapping can be corrected.
    source_rows = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=12, choices=BatchStatus.choices, default="PREVIEW")
    insert_count = models.PositiveIntegerField(default=0)
    update_count = models.PositiveIntegerField(default=0)
    unchanged_count = models.PositiveIntegerField(default=0)
    withheld_count = models.PositiveIntegerField(default=0)
    queued_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    rolled_back_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "id"]

    def __str__(self) -> str:
        return f"import batch {self.pk}"


class RowState(models.TextChoices):
    READY = "READY", "Ready"
    WITHHELD = "WITHHELD", "Withheld"
    QUEUED = "QUEUED", "In review queue"
    IMPORTED = "IMPORTED", "Imported"
    UPDATED = "UPDATED", "Updated"
    UNCHANGED = "UNCHANGED", "Unchanged"
    LINKED = "LINKED", "Linked to existing"
    CREATED = "CREATED", "Created new person"
    SKIPPED = "SKIPPED", "Skipped"


class ImportRow(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="rows")
    row_number = models.PositiveIntegerField()
    external_id = models.CharField(max_length=128, blank=True)
    row_hash = models.CharField(max_length=64)
    data = models.JSONField(default=dict)
    state = models.CharField(max_length=10, choices=RowState.choices, default=RowState.READY)
    reason = models.CharField(max_length=200, blank=True)
    candidate_profile = models.ForeignKey(
        "talent.TalentProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    profile = models.ForeignKey(
        "talent.TalentProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["row_number"]

    def __str__(self) -> str:
        return f"import row {self.pk}"


class SourceRecord(TenantModel):
    """The last imported hash per source key, so an identical row causes no write."""

    profile = models.OneToOneField(
        "talent.TalentProfile", on_delete=models.CASCADE, related_name="source_record"
    )
    row_hash = models.CharField(max_length=64)
    batch = models.ForeignKey(ImportBatch, on_delete=models.SET_NULL, null=True, related_name="+")

    def __str__(self) -> str:
        return f"source record {self.pk}"


class FieldChange(TenantModel):
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="changes")
    profile = models.ForeignKey("talent.TalentProfile", on_delete=models.CASCADE)
    field = models.CharField(max_length=64)
    previous_value = models.JSONField(null=True)
    imported_value = models.JSONField(null=True)
    created = models.BooleanField(default=False)
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["changed_at", "id"]

    def __str__(self) -> str:
        return f"field change {self.pk}"
