"""Profile and skill-claim rules, shared by the screens and the API."""

from datetime import date

from django.db import transaction

from apps.matching.vocabulary import resolve_skill

from .models import ClaimProvenance, ResourceType, SkillClaim

MAX_MONTHS = 1200
MAX_NOTICE_DAYS = 3650


class ProfileInvalid(Exception):
    def __init__(self, errors):
        super().__init__(errors)
        self.errors = errors


def validate_profile(data, resource_type):
    """Errors name the field. Internal consultants need allocation and an available-from date."""
    errors = {}
    if not (data.get("title") or "").strip():
        errors["title"] = "Enter a title."
    if not (data.get("display_name") or "").strip():
        errors["display_name"] = "Enter a name."
    allocation = data.get("allocation_pct")
    if allocation not in (None, "") and not 0 <= int(allocation) <= 100:
        errors["allocation_pct"] = "Allocation must be between 0 and 100."
    if resource_type == ResourceType.INTERNAL:
        if allocation in (None, ""):
            errors["allocation_pct"] = "Enter the current allocation."
        if not data.get("available_from"):
            errors["available_from"] = "Enter the available-from date."
    notice = data.get("notice_days")
    if notice not in (None, "") and not 0 <= int(notice) <= MAX_NOTICE_DAYS:
        errors["notice_days"] = f"Notice period must be between 0 and {MAX_NOTICE_DAYS} days."
    available = data.get("available_from")
    if isinstance(available, str) and available:
        try:
            date.fromisoformat(available)
        except ValueError:
            errors["available_from"] = "Enter a date, YYYY-MM-DD."
    if errors:
        raise ProfileInvalid(errors)


def valid_months(months):
    if months in (None, ""):
        return None
    try:
        value = int(months)
    except (TypeError, ValueError) as error:
        raise ProfileInvalid({"months": "Enter months as a whole number."}) from error
    if not 0 <= value <= MAX_MONTHS:
        raise ProfileInvalid({"months": f"Months must be between 0 and {MAX_MONTHS}."})
    return value


@transaction.atomic
def add_form_claim(profile, skill_name, months=None):
    """Add one structured claim. A repeat, directly or through an alias, leaves one claim."""
    skill = resolve_skill(str(skill_name or ""))
    if skill is None:
        raise ProfileInvalid({"skill": "Pick a skill from the list."})
    months = valid_months(months)
    claim, _created = SkillClaim.objects.update_or_create(
        profile=profile,
        skill=skill,
        defaults={"provenance": ClaimProvenance.FORM, "months": months, "confirmed": True},
    )
    return claim
