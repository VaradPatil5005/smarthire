"""Projects and their versioned rubrics. An approved rubric can never change."""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.tenancy.models import TenantModel


class RubricLocked(Exception):
    """An approved rubric version was about to change."""


class ProjectStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    OPEN = "OPEN", "Open"
    CLOSED = "CLOSED", "Closed"


class Project(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=10, choices=ProjectStatus.choices, default=ProjectStatus.DRAFT
    )
    start_date = models.DateField(null=True, blank=True)
    required_allocation_pct = models.PositiveSmallIntegerField(default=100)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(required_allocation_pct__gt=0, required_allocation_pct__lte=100),
                name="required_allocation_between_1_and_100",
            )
        ]

    def __str__(self) -> str:
        return f"project {self.pk}"

    @property
    def is_closed(self) -> bool:
        return self.status == ProjectStatus.CLOSED

    def latest_rubric(self):
        return self.rubrics.order_by("-version").first()

    def latest_approved_rubric(self):
        return self.rubrics.filter(status=RubricStatus.APPROVED).order_by("-version").first()


class RubricStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    APPROVED = "APPROVED", "Approved"


class GuardedRubricQuerySet(models.QuerySet):
    def _refuse_if_approved(self):
        if self.filter(status=RubricStatus.APPROVED).exists():
            raise RubricLocked

    def update(self, **kwargs):
        self._refuse_if_approved()
        return super().update(**kwargs)

    def delete(self):
        self._refuse_if_approved()
        return super().delete()

    def bulk_update(self, objs, fields, **kwargs):
        if any(obj.status == RubricStatus.APPROVED for obj in objs):
            raise RubricLocked
        return super().bulk_update(objs, fields, **kwargs)


class RubricVersion(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="rubrics")
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=RubricStatus.choices, default="DRAFT")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    objects = GuardedRubricQuerySet.as_manager()

    class Meta:
        ordering = ["project_id", "version"]
        constraints = [
            models.UniqueConstraint(fields=["project", "version"], name="unique_rubric_version")
        ]

    def __str__(self) -> str:
        return f"rubric {self.pk}"

    def save(self, *args, **kwargs):
        if self.pk:
            stored = RubricVersion.objects.filter(pk=self.pk).values_list("status", flat=True)
            if stored.first() == RubricStatus.APPROVED:
                raise RubricLocked
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        _refuse_approved_rubrics([self.pk])
        return super().delete(*args, **kwargs)

    @property
    def is_approved(self) -> bool:
        return self.status == RubricStatus.APPROVED


class Importance(models.TextChoices):
    REQUIRED = "REQUIRED", "Required"
    PREFERRED = "PREFERRED", "Preferred"


class GuardedSkillQuerySet(models.QuerySet):
    def _refuse_if_approved(self):
        if self.filter(rubric__status=RubricStatus.APPROVED).exists():
            raise RubricLocked

    def update(self, **kwargs):
        self._refuse_if_approved()
        target = kwargs.get("rubric", kwargs.get("rubric_id"))
        if target is not None:
            target_id = getattr(target, "pk", target)
            # SQL expressions cannot be checked as a single destination rubric.
            if not isinstance(target_id, int):
                raise RubricLocked
            _refuse_approved_rubrics([target_id])
        return super().update(**kwargs)

    def delete(self):
        self._refuse_if_approved()
        return super().delete()

    def bulk_create(self, objs, *args, **kwargs):
        objs = list(objs)
        _refuse_approved_rubrics([obj.rubric_id for obj in objs])
        return super().bulk_create(objs, *args, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        objs = list(objs)
        _refuse_approved_rubrics([obj.rubric_id for obj in objs])
        self.filter(pk__in=[obj.pk for obj in objs])._refuse_if_approved()
        return super().bulk_update(objs, fields, **kwargs)


def _refuse_approved_rubrics(rubric_ids):
    """Read current state; related objects may have been cached before approval."""
    if RubricVersion.objects.filter(pk__in=rubric_ids, status=RubricStatus.APPROVED).exists():
        raise RubricLocked


class RequirementSkill(models.Model):
    rubric = models.ForeignKey(RubricVersion, on_delete=models.CASCADE, related_name="skills")
    skill = models.ForeignKey("matching.SkillNode", on_delete=models.PROTECT)
    importance = models.CharField(max_length=10, choices=Importance.choices)
    weight = models.IntegerField()
    required_months = models.PositiveSmallIntegerField(default=0)

    objects = GuardedSkillQuerySet.as_manager()

    class Meta:
        ordering = ["-importance", "-weight", "id"]
        constraints = [
            models.UniqueConstraint(fields=["rubric", "skill"], name="unique_skill_per_rubric"),
            models.CheckConstraint(condition=Q(weight__gt=0), name="rubric_weight_positive"),
        ]

    def __str__(self) -> str:
        return f"requirement {self.pk}"

    def save(self, *args, **kwargs):
        _refuse_approved_rubrics([self.rubric_id])
        if self.pk:
            RequirementSkill.objects.filter(pk=self.pk)._refuse_if_approved()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        _refuse_approved_rubrics([self.rubric_id])
        if self.pk:
            RequirementSkill.objects.filter(pk=self.pk)._refuse_if_approved()
        return super().delete(*args, **kwargs)
