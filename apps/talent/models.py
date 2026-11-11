"""One profile model for bench consultants and external applicants."""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.tenancy.models import TenantModel


class ResourceType(models.TextChoices):
    EXTERNAL = "EXTERNAL", "External applicant"
    INTERNAL = "INTERNAL", "Internal consultant"


class TalentProfile(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    resource_type = models.CharField(
        max_length=10, choices=ResourceType.choices, default=ResourceType.EXTERNAL
    )
    display_name = models.CharField(max_length=200)
    title = models.CharField(max_length=200)
    # Contact and background fields are display-only. No scoring input reads them.
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    college = models.CharField(max_length=200, blank=True)
    # Availability feeds Staffing fit only, never Coverage.
    allocation_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    available_from = models.DateField(null=True, blank=True)
    notice_days = models.PositiveSmallIntegerField(null=True, blank=True)
    # The only keys an import may match on.
    source_system = models.CharField(max_length=64, blank=True)
    external_id = models.CharField(max_length=128, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "source_system", "external_id"],
                condition=~Q(external_id=""),
                name="unique_source_key_per_organisation",
            ),
            models.UniqueConstraint(
                fields=["organisation", "owner"],
                condition=Q(owner__isnull=False),
                name="one_profile_per_owner_per_organisation",
            ),
            models.CheckConstraint(
                condition=Q(allocation_pct__isnull=True) | Q(allocation_pct__lte=100),
                name="allocation_pct_at_most_100",
            ),
        ]

    def __str__(self) -> str:
        return f"profile {self.pk}"


class ClaimProvenance(models.TextChoices):
    FORM = "FORM", "Form claim"
    IMPORT = "IMPORT", "Imported"


class SkillClaim(models.Model):
    """A structured claim. A form claim is Self-reported; an unconfirmed import earns nothing."""

    profile = models.ForeignKey(TalentProfile, on_delete=models.CASCADE, related_name="claims")
    skill = models.ForeignKey("matching.SkillNode", on_delete=models.PROTECT)
    provenance = models.CharField(max_length=10, choices=ClaimProvenance.choices)
    months = models.PositiveSmallIntegerField(null=True, blank=True)
    confirmed = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["profile", "skill"], name="unique_claim_per_skill")
        ]

    def __str__(self) -> str:
        return f"claim {self.pk}"


class DataRequest(TenantModel):
    """A candidate's correction or deletion request, for a staff role to act on. No free text."""

    class Kind(models.TextChoices):
        CORRECTION = "CORRECTION", "Correction"
        DELETION = "DELETION", "Deletion"

    profile = models.ForeignKey(TalentProfile, on_delete=models.CASCADE)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    created_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"data request {self.pk}"
