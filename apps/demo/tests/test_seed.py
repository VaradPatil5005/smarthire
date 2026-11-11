from decimal import Decimal

import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings

from apps.matching.services import create_run
from apps.projects.models import Project
from apps.projects.services import approve_rubric
from apps.talent.models import ResourceType, TalentProfile
from apps.tenancy.models import Organisation, Role

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    with override_settings(DEBUG=True):
        call_command("seed_demo", verbosity=0)
    return Organisation.objects.get(slug="weplm-demo")


def test_seed_loads_2_orgs_3_projects_24_profiles_with_a_bench(seeded):
    """AC-PROJ-15"""
    assert Organisation.objects.count() == 2
    assert Project.objects.count() == 3
    assert TalentProfile.objects.count() == 24
    assert TalentProfile.objects.filter(resource_type=ResourceType.INTERNAL).count() == 8


def test_seed_is_safe_to_run_twice(seeded):
    """AC-PROJ-15"""
    with override_settings(DEBUG=True):
        call_command("seed_demo", verbosity=0)
    assert TalentProfile.objects.count() == 24


def test_seed_refuses_with_debug_off():
    """AC-PROJ-15: it creates known logins."""
    with override_settings(DEBUG=False), pytest.raises(CommandError):
        call_command("seed_demo", verbosity=0)


def test_seeded_demo_reproduces_65_and_70(seeded):
    """AC-MATCH-15, AC-MATCH-16"""
    project = Project.objects.for_org(seeded).get(name__startswith="3DEXPERIENCE migration")
    from django.contrib.auth import get_user_model

    manager = get_user_model().objects.get(username="manager")
    assert manager.membership_set.get().role == Role.DELIVERY_MANAGER
    approve_rubric(project.latest_rubric(), manager)
    run, _created = create_run(project, "k", {}, manager, seeded)
    by_name = {r.profile.display_name: r for r in run.results.select_related("profile")}
    assert by_name["Fictional Candidate A"].coverage == Decimal("65.00")
    assert by_name["Fictional Candidate B"].coverage == Decimal("70.00")
    assert run.results.count() == 22


def test_dark_banner_resume_is_not_flagged(seeded):
    """AC-DASH-20"""
    banner = TalentProfile.objects.get(display_name="Honest Banner Candidate")
    assert banner.resumes.get().status == "CLEAN"
