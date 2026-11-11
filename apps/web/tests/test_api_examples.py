"""Runs docs/api/examples.md: one allowed, one denied example per role, 8 of 8, on seeded data."""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings

from apps.projects.models import Project
from tests.factories.world import client_for

pytestmark = pytest.mark.django_db
JSON = "application/json"
HEADER = b"Emp ID,Emp Name\nE1,Fictional One\n"


@pytest.fixture
def clients():
    with override_settings(DEBUG=True):
        call_command("seed_demo", verbosity=0)
    users = get_user_model().objects
    return {
        name: client_for(users.get(username=name))
        for name in ("candidate_a", "recruiter", "manager", "admin", "other_recruiter")
    }


@pytest.fixture
def project(clients):
    return Project.objects.get(name__startswith="3DEXPERIENCE migration")


def _approve(client, project):
    return client.post(f"/api/projects/{project.pk}/rubrics/1/approve/", {}, JSON)


def _import(client):
    upload = SimpleUploadedFile("r.csv", HEADER)
    return client.post("/api/imports/", {"file": upload, "source_system": "HR"})


def test_candidate_examples(clients, project):
    """AC-AUTH-16"""
    allowed = clients["candidate_a"].get("/api/profiles/me/")
    assert allowed.status_code == 200
    assert allowed.json()["display_name"] == "Fictional Candidate A"
    assert _approve(clients["candidate_a"], project).status_code == 403


def test_recruiter_examples(clients, project):
    """AC-AUTH-16"""
    assert _approve(clients["recruiter"], project).status_code == 403
    assert _approve(clients["manager"], project).status_code == 200
    url = f"/api/projects/{project.pk}/runs/"
    run = clients["recruiter"].post(url, {}, JSON, HTTP_IDEMPOTENCY_KEY="demo-1")
    assert run.status_code == 201
    assert run.json()["algorithm_version"] == "1.1"
    conflict = clients["recruiter"].post(
        url, {"run_date": "2026-01-01"}, JSON, HTTP_IDEMPOTENCY_KEY="demo-1"
    )
    assert conflict.status_code == 409


def test_delivery_manager_examples(clients, project):
    """AC-AUTH-16"""
    allowed = _approve(clients["manager"], project)
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "APPROVED"
    assert _import(clients["manager"]).status_code == 403


def test_admin_examples(clients, project):
    """AC-AUTH-16"""
    allowed = _import(clients["admin"])
    assert allowed.status_code == 201
    assert allowed.json()["status"] == "PREVIEW"
    assert clients["other_recruiter"].get(f"/api/projects/{project.pk}/").status_code == 404
