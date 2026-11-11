"""Rubric life cycle: draft, approve and lock, then copy to the next version to change anything."""

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.models import record_event
from apps.matching.vocabulary import resolve_skill

from .models import Importance, ProjectStatus, RequirementSkill, RubricLocked, RubricVersion


class RubricInvalid(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _whole_number(value, field, minimum, maximum):
    try:
        if isinstance(value, bool):
            raise ValueError
        number = int(str(value).strip())
    except (TypeError, ValueError) as error:
        raise RubricInvalid(f"{field} must be a whole number.") from error
    if field == "Weight" and number < minimum:
        raise RubricInvalid("Weight must be greater than 0.")
    if not minimum <= number <= maximum:
        raise RubricInvalid(f"{field} must be between {minimum} and {maximum}.")
    return number


def add_skill(rubric, skill_name, importance, weight, required_months=0):
    if rubric.is_approved:
        raise RubricLocked
    skill = resolve_skill(skill_name)
    if skill is None:
        raise RubricInvalid("Pick a skill from the vocabulary.")
    if importance not in Importance.values:
        raise RubricInvalid("Importance must be required or preferred.")
    weight = _whole_number(weight, "Weight", 1, 2147483647)
    required_months = _whole_number(required_months, "Required months", 0, 32767)
    try:
        with transaction.atomic():
            return RequirementSkill.objects.create(
                rubric=rubric,
                skill=skill,
                importance=importance,
                weight=weight,
                required_months=required_months,
            )
    except IntegrityError as error:
        raise RubricInvalid("This skill is already in the rubric.") from error


def update_skill_weight(item, weight, actor):
    item.weight = _whole_number(weight, "Weight", 1, 2147483647)
    item.save()
    record_event(item.rubric.project.organisation, actor, "rubric.weight_changed", item)
    return item


def update_skill(item, weight, importance, required_months, actor):
    """Change one row of a draft. A locked rubric refuses it in the model."""
    weight = _whole_number(weight, "Weight", 1, 2147483647)
    if importance not in Importance.values:
        raise RubricInvalid("Importance must be required or preferred.")
    required_months = _whole_number(required_months, "Required months", 0, 32767)
    item.weight = weight
    item.importance = importance
    item.required_months = required_months
    item.save()
    record_event(item.rubric.project.organisation, actor, "rubric.skill_changed", item)
    return item


@transaction.atomic
def approve_rubric(rubric, actor) -> RubricVersion:
    if rubric.is_approved:
        raise RubricLocked
    if not rubric.skills.exists():
        raise RubricInvalid("A rubric needs at least one skill before approval.")
    RubricVersion.objects.filter(pk=rubric.pk).update(
        status="APPROVED", approved_by=actor, approved_at=timezone.now()
    )
    project = rubric.project
    if project.status == ProjectStatus.DRAFT:
        project.status = ProjectStatus.OPEN
        project.save(update_fields=["status"])
    record_event(project.organisation, actor, "rubric.approved", rubric)
    rubric.refresh_from_db()
    return rubric


@transaction.atomic
def next_version(project) -> RubricVersion:
    """Start a draft from the latest version. An existing draft is returned; v1 stays untouched."""
    latest = project.latest_rubric()
    if latest is None:
        return RubricVersion.objects.create(project=project, version=1)
    if not latest.is_approved:
        return latest
    draft = RubricVersion.objects.create(project=project, version=latest.version + 1)
    RequirementSkill.objects.bulk_create(
        [
            RequirementSkill(
                rubric=draft,
                skill_id=item.skill_id,
                importance=item.importance,
                weight=item.weight,
                required_months=item.required_months,
            )
            for item in latest.skills.all()
        ]
    )
    return draft
