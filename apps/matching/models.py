"""The skill vocabulary, the evidence ledger, and stored match runs."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.tenancy.models import TenantModel

ALGORITHM_VERSION = "1.1"


class SkillCategory(models.TextChoices):
    PLM = "PLM", "PLM"
    BACKEND = "BACKEND", "Backend"
    DATA = "DATA", "Data"
    CLOUD = "CLOUD", "Cloud"
    PRACTICE = "PRACTICE", "Practice"


class SkillNode(models.Model):
    """Global reference data. A parent is what a child implies, never the reverse."""

    canonical_name = models.CharField(max_length=120, unique=True)
    category = models.CharField(max_length=10, choices=SkillCategory.choices)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )

    class Meta:
        ordering = ["canonical_name"]

    def __str__(self) -> str:
        return self.canonical_name


class DictionaryVersion(models.Model):
    number = models.PositiveIntegerField(unique=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-number"]

    def __str__(self) -> str:
        return f"dictionary v{self.number}"


class SkillAlias(models.Model):
    text = models.CharField(max_length=120)
    skill = models.ForeignKey(SkillNode, on_delete=models.PROTECT, related_name="aliases")
    dictionary_version = models.ForeignKey(
        DictionaryVersion, on_delete=models.PROTECT, related_name="aliases"
    )
    approved_by = models.CharField(max_length=120, default="seed pack")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["text", "dictionary_version"], name="unique_alias_per_dictionary"
            )
        ]

    def __str__(self) -> str:
        return self.text


class Section(models.TextChoices):
    EXPERIENCE = "EXPERIENCE", "Work experience"
    PROJECT = "PROJECT", "Project"
    SKILLS = "SKILLS", "Skills list"
    OTHER = "OTHER", "Other"


class SpanState(models.TextChoices):
    PROVISIONAL = "PROVISIONAL", "Provisional"
    ACCEPTED = "ACCEPTED", "Accepted"
    EXCLUDED = "EXCLUDED", "Excluded by reviewer"
    NEGATED = "NEGATED", "Negated"
    ASPIRATIONAL = "ASPIRATIONAL", "Aspirational"
    NOTICE = "NOTICE", "Instruction-like notice"


UNACCEPTABLE_STATES = frozenset({SpanState.NEGATED, SpanState.ASPIRATIONAL, SpanState.NOTICE})


class EvidenceSpan(TenantModel):
    """A passage in the visible text that may support a skill. Nothing counts until accepted."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        "talent.TalentProfile", on_delete=models.CASCADE, related_name="spans"
    )
    resume_version = models.ForeignKey(
        "ingestion.ResumeVersion", on_delete=models.CASCADE, related_name="spans"
    )
    skill = models.ForeignKey(SkillNode, on_delete=models.PROTECT)
    page = models.PositiveSmallIntegerField()
    start = models.PositiveIntegerField()
    end = models.PositiveIntegerField()
    quote = models.TextField()
    section = models.CharField(max_length=10, choices=Section.choices)
    state = models.CharField(
        max_length=12, choices=SpanState.choices, default=SpanState.PROVISIONAL
    )
    ambiguous = models.BooleanField(default=False)
    months = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["page", "start"]
        constraints = [
            models.UniqueConstraint(
                fields=["resume_version", "start", "end", "skill"], name="unique_span"
            )
        ]

    def __str__(self) -> str:
        return f"span {self.pk}"


class Outcome(models.TextChoices):
    ACCEPT = "ACCEPT", "Accept"
    EXCLUDE = "EXCLUDE", "Exclude"
    VERIFIED = "VERIFIED", "Verified"
    UNMET = "UNMET", "Unmet must-have"
    OVERRIDE = "OVERRIDE", "Recruiter override"


class Method(models.TextChoices):
    NONE = "", "None"
    TEST = "TEST", "Test"
    INTERVIEW = "INTERVIEW", "Interview"


class ReviewDecision(TenantModel):
    """Every human decision: who, when, what and why."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(default=timezone.now)
    outcome = models.CharField(max_length=10, choices=Outcome.choices)
    reason = models.TextField()
    profile = models.ForeignKey("talent.TalentProfile", on_delete=models.CASCADE)
    skill = models.ForeignKey(SkillNode, null=True, blank=True, on_delete=models.PROTECT)
    span = models.ForeignKey(EvidenceSpan, null=True, blank=True, on_delete=models.CASCADE)
    method = models.CharField(max_length=10, choices=Method.choices, blank=True, default="")

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(condition=~models.Q(reason=""), name="decision_needs_reason")
        ]

    def __str__(self) -> str:
        return f"decision {self.pk}"


class RunStatus(models.TextChoices):
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"


class MatchRun(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="runs")
    rubric_version = models.ForeignKey("projects.RubricVersion", on_delete=models.PROTECT)
    dictionary_version = models.ForeignKey(DictionaryVersion, on_delete=models.PROTECT)
    algorithm_version = models.CharField(max_length=10, default=ALGORITHM_VERSION)
    run_date = models.DateField()
    idempotency_key = models.CharField(max_length=128)
    payload_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=10, choices=RunStatus.choices, default="COMPLETED")
    inputs = models.JSONField(default=dict)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "idempotency_key"], name="unique_idempotency_key_per_org"
            )
        ]

    def __str__(self) -> str:
        return f"run {self.pk}"

    def save(self, *args, **kwargs):
        if self.project.organisation_id != self.organisation_id:
            raise ValidationError("A run and its project must share one organisation")
        super().save(*args, **kwargs)


class ReviewGroup(models.TextChoices):
    READY = "READY", "Ready for review"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION", "Needs clarification"
    UNMET = "UNMET", "Unmet must-have"


class MatchResult(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(MatchRun, on_delete=models.CASCADE, related_name="results")
    profile = models.ForeignKey("talent.TalentProfile", on_delete=models.CASCADE)
    # Frozen at run time, so an old shortlist reads, filters and exports as it did on the day.
    name_snapshot = models.CharField(max_length=200, default="")
    resource_type_snapshot = models.CharField(
        max_length=10,
        default="",
        choices=[("EXTERNAL", "External applicant"), ("INTERNAL", "Internal consultant")],
    )
    coverage = models.DecimalField(max_digits=5, decimal_places=2)
    staffing_fit = models.DecimalField(max_digits=5, decimal_places=2)
    mandatory_coverage = models.DecimalField(max_digits=5, decimal_places=2)
    missing_must_haves = models.PositiveSmallIntegerField()
    review_group = models.CharField(max_length=20, choices=ReviewGroup.choices)
    rank = models.PositiveIntegerField()
    position = models.PositiveIntegerField()
    availability_unknown = models.BooleanField(default=False)
    group_reason = models.CharField(max_length=200, blank=True)
    inputs = models.JSONField(default=dict)
    change_reasons = models.JSONField(default=list)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["run", "profile"], name="unique_result_per_profile")
        ]

    def __str__(self) -> str:
        return f"result {self.pk}"

    def save(self, *args, **kwargs):
        if self.profile.organisation_id != self.run.organisation_id:
            raise ValidationError("A result and its profile must share one organisation")
        super().save(*args, **kwargs)


class SkillContribution(models.Model):
    result = models.ForeignKey(MatchResult, on_delete=models.CASCADE, related_name="contributions")
    skill = models.ForeignKey(SkillNode, on_delete=models.PROTECT)
    importance = models.CharField(max_length=10)
    weight = models.IntegerField()
    evidence_factor = models.DecimalField(max_digits=3, decimal_places=2)
    credit = models.DecimalField(max_digits=5, decimal_places=4)
    label = models.CharField(max_length=20)
    bucket = models.CharField(max_length=12)
    duration_estimated = models.BooleanField(default=False)
    evidence_span = models.ForeignKey(
        EvidenceSpan, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-weight", "id"]

    def __str__(self) -> str:
        return f"contribution {self.pk}"
