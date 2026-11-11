"""Builders for the domain: organisations, users, profiles, rubrics, résumés. Synthetic data."""

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.ingestion import services as ingestion
from apps.matching.models import EvidenceSpan, Outcome
from apps.matching.services import decide_span
from apps.matching.vocabulary import load_seed_pack
from apps.projects.models import Importance, Project
from apps.projects.services import add_skill, approve_rubric, next_version
from apps.talent.models import ResourceType, TalentProfile
from apps.tenancy.models import Membership, Organisation, Role

FIXTURES = Path(settings.BASE_DIR) / "fixtures" / "pdf"
WORKED_RUBRIC = (
    ("ENOVIA configuration", Importance.REQUIRED, 5),
    ("Migration validation", Importance.REQUIRED, 3),
    ("Python automation", Importance.PREFERRED, 2),
)
_counter = {"n": 0}


def _next():
    _counter["n"] += 1
    return _counter["n"]


def make_org(name=None):
    number = _next()
    return Organisation.objects.create(name=name or f"Org {number}", slug=f"org-{number}")


def make_user(org, role=Role.RECRUITER, username=None):
    user = get_user_model().objects.create_user(
        username=username or f"user{_next()}", password="test-only-password-1"
    )
    Membership.objects.create(user=user, organisation=org, role=role)
    return user


def client_for(user):
    client = Client()
    client.force_login(user)
    return client


def make_profile(org, name=None, resource_type=ResourceType.EXTERNAL, **kwargs):
    return TalentProfile.objects.create(
        organisation=org,
        display_name=name or f"Fictional Person {_next()}",
        title=kwargs.pop("title", "PLM Consultant"),
        resource_type=resource_type,
        **kwargs,
    )


def make_project(org, skills=WORKED_RUBRIC, approved=True, approver=None, **kwargs):
    load_seed_pack()
    project = Project.objects.create(
        organisation=org, name=kwargs.pop("name", f"Fictional project {_next()}"), **kwargs
    )
    rubric = next_version(project)
    for skill, importance, weight in skills:
        add_skill(rubric, skill, importance, weight)
    if approved:
        approve_rubric(rubric, approver)
    return project


def fixture_bytes(name):
    return (FIXTURES / f"{name}.pdf").read_bytes()


def upload_fixture(name, profile, user=None):
    """Upload through the real path and run the real scan, inline."""
    load_seed_pack()
    uploaded = SimpleUploadedFile(
        f"{name}.pdf", fixture_bytes(name), content_type="application/pdf"
    )
    version = ingestion.receive_upload(uploaded, profile, profile.organisation, user)
    ingestion.scan_stored_version(version.pk)
    version.refresh_from_db()
    return version


def accept_spans(profile, reviewer, skills=None):
    spans = EvidenceSpan.objects.filter(profile=profile, state="PROVISIONAL")
    if skills is not None:
        spans = spans.filter(skill__canonical_name__in=skills)
    decisions = []
    for span in spans:
        decisions.append(
            decide_span(span, Outcome.ACCEPT, "Reviewed.", reviewer, profile.organisation)
        )
    return decisions
