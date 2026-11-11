"""A recruiter can correct ordinary mistakes in the browser, with no API client or database."""

from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.matching.models import EvidenceSpan, ReviewDecision
from apps.matching.services import create_run
from apps.onboarding.models import BatchStatus, ImportBatch, ImportRow, RowState
from apps.projects.models import RequirementSkill
from apps.talent.models import DataRequest, ResourceType, TalentProfile
from apps.tenancy.models import Role
from tests.factories.world import (
    client_for,
    make_org,
    make_profile,
    make_project,
    make_user,
    upload_fixture,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return make_org()


@pytest.fixture
def staff(org):
    make_project(org)
    return make_user(org, Role.DELIVERY_MANAGER)


@pytest.fixture
def client(staff):
    return client_for(staff)


def test_staff_edit_a_profile_including_allocation_and_availability(org, client):
    """AC-CAND-02"""
    profile = make_profile(org, name="Old Name", resource_type=ResourceType.INTERNAL)
    url = f"/profiles/{profile.pk}/edit/"
    assert b"Old Name" in client.get(url).content
    response = client.post(
        url,
        {
            "display_name": "New Name",
            "title": "Architect",
            "resource_type": "INTERNAL",
            "allocation_pct": "40",
            "available_from": "2026-12-01",
        },
    )
    assert response.status_code == 302
    profile.refresh_from_db()
    assert (profile.display_name, profile.allocation_pct) == ("New Name", 40)
    assert profile.available_from == date(2026, 12, 1)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("title", "", "Enter a title"),
        ("allocation_pct", "101", "Allocation must be"),
        ("available_from", "junk", "Enter a date"),
    ],
)
def test_bad_profile_edits_show_the_error_and_save_nothing(org, client, field, value, error):
    """AC-CAND-03"""
    profile = make_profile(org, name="Keep Me")
    data = {"display_name": "Changed", "title": "T", "resource_type": "EXTERNAL", field: value}
    response = client.post(f"/profiles/{profile.pk}/edit/", data)
    assert response.status_code == 200
    assert error in response.content.decode()
    profile.refresh_from_db()
    assert profile.display_name == "Keep Me"


def test_failed_profile_creation_retains_the_values_to_correct(client):
    response = client.post(
        "/profiles/",
        {
            "display_name": "Keep These Details",
            "title": "Architect",
            "resource_type": "INTERNAL",
            "allocation_pct": "wrong",
            "available_from": "2026-12-01",
        },
    )
    html = response.content.decode()
    assert 'value="Keep These Details"' in html
    assert 'value="Architect"' in html
    assert 'value="INTERNAL" selected' in html
    assert response.context["errors"] == {"allocation_pct": "Enter a whole number."}


def test_failed_candidate_edit_retains_the_submitted_name(org):
    user = make_user(org, Role.CANDIDATE)
    profile = make_profile(org, owner=user, name="Saved Name")
    response = client_for(user).post("/me/", {"display_name": "Corrected Name", "title": ""})
    assert 'value="Corrected Name"' in response.content.decode()
    profile.refresh_from_db()
    assert profile.display_name == "Saved Name"


def test_import_queue_and_dashboard_only_offer_confirmed_batch_rows(org):
    admin = client_for(make_user(org, Role.ADMIN))
    for status in BatchStatus.values:
        batch = ImportBatch.objects.create(
            organisation=org, source_system=status, source_digest=status, status=status
        )
        ImportRow.objects.create(
            organisation=org,
            batch=batch,
            row_number=1,
            row_hash=status,
            state=RowState.QUEUED,
            data={"display_name": f"Incoming {status}"},
        )
    response = admin.get("/imports/queue/")
    assert response.status_code == 200
    html = response.content.decode()
    assert "Incoming CONFIRMED" in html
    assert "Incoming PREVIEW" not in html
    assert "Incoming ROLLED_BACK" not in html
    assert admin.get("/dashboard/").context["queued"] == 1


def test_candidate_cannot_use_staff_edit(org):
    """AC-AUTH-15"""
    profile = make_profile(org)
    candidate = client_for(make_user(org, Role.CANDIDATE))
    assert candidate.get(f"/profiles/{profile.pk}/edit/").status_code == 403


def test_edit_project_details(org, client):
    """AC-PROJ-02"""
    project = make_project(org, approved=False, name="Old Project")
    url = f"/projects/{project.pk}/edit/"
    assert b"Old Project" in client.get(url).content
    client.post(
        url, {"name": "New Project", "start_date": "2027-01-15", "required_allocation_pct": "50"}
    )
    project.refresh_from_db()
    assert project.name == "New Project"
    assert project.required_allocation_pct == 50
    assert project.start_date == date(2027, 1, 15)


def test_closed_project_cannot_be_edited(org, client):
    """AC-PROJ-02"""
    project = make_project(org, approved=False, name="Stays")
    client.post(f"/projects/{project.pk}/close/")
    client.post(f"/projects/{project.pk}/edit/", {"name": "Changed"})
    project.refresh_from_db()
    assert project.name == "Stays"


def test_change_weight_and_months_on_a_draft(org, client):
    """AC-PROJ-03, AC-PROJ-16"""
    project = make_project(org, approved=False)
    item = project.latest_rubric().skills.first()
    url = f"/projects/{project.pk}/skills/{item.pk}/"
    client.post(url, {"weight": "9", "required_months": "12", "importance": "PREFERRED"})
    item.refresh_from_db()
    assert (item.weight, item.required_months, item.importance) == (9, 12, "PREFERRED")


def test_bad_weight_is_a_message_and_changes_nothing(org, client):
    """AC-PROJ-04"""
    project = make_project(org, approved=False)
    item = project.latest_rubric().skills.first()
    before = item.weight
    response = client.post(
        f"/projects/{project.pk}/skills/{item.pk}/", {"weight": "0"}, follow=True
    )
    assert b"greater than 0" in response.content
    item.refresh_from_db()
    assert item.weight == before


def test_remove_a_skill_from_a_draft(org, client):
    """AC-PROJ-03"""
    project = make_project(org, approved=False)
    item = project.latest_rubric().skills.first()
    client.post(f"/projects/{project.pk}/skills/{item.pk}/remove/")
    assert not RequirementSkill.objects.filter(pk=item.pk).exists()


def test_approved_rubric_refuses_edit_and_removal_in_the_browser(org, client, staff):
    """AC-PROJ-08"""
    project = make_project(org, approver=staff)
    item = project.latest_rubric().skills.first()
    edited = client.post(f"/projects/{project.pk}/skills/{item.pk}/", {"weight": "9"}, follow=True)
    assert b"locked" in edited.content
    removed = client.post(f"/projects/{project.pk}/skills/{item.pk}/remove/", follow=True)
    assert b"locked" in removed.content
    item.refresh_from_db()
    assert item.weight != 9


def test_a_skill_id_from_another_project_is_404(org, client):
    """AC-AUTH-09"""
    project = make_project(org, approved=False)
    other = make_project(org, approved=False).latest_rubric().skills.first()
    response = client.post(f"/projects/{project.pk}/skills/{other.pk}/", {"weight": "9"})
    assert response.status_code == 404


def test_reviewer_records_months_and_reverses_a_decision_on_the_screen(org, client):
    """AC-MATCH-25, AC-MATCH-19"""
    profile = make_profile(org)
    upload_fixture("demo_candidate_a", profile)
    span = EvidenceSpan.objects.filter(profile=profile, state="PROVISIONAL").first()
    url = f"/profiles/{profile.pk}/decide/"
    client.post(
        url, {"span_id": str(span.pk), "outcome": "ACCEPT", "reason": "Fine.", "months": "24"}
    )
    span.refresh_from_db()
    assert (span.state, span.months) == ("ACCEPTED", 24)
    page = client.get(f"/profiles/{profile.pk}/").content.decode()
    assert "Fine." in page
    assert 'value="EXCLUDE"' in page
    client.post(url, {"span_id": str(span.pk), "outcome": "EXCLUDE", "reason": "Misread it."})
    span.refresh_from_db()
    assert span.state == "EXCLUDED"
    assert ReviewDecision.objects.filter(span=span).count() == 2


def test_bad_months_on_the_screen_shows_a_plain_message(org, client):
    """AC-MATCH-25"""
    profile = make_profile(org)
    upload_fixture("demo_candidate_a", profile)
    span = EvidenceSpan.objects.filter(profile=profile, state="PROVISIONAL").first()
    response = client.post(
        f"/profiles/{profile.pk}/decide/",
        {"span_id": str(span.pk), "outcome": "ACCEPT", "reason": "Fine.", "months": "abc"},
        follow=True,
    )
    assert b"whole number" in response.content
    assert b"invalid literal" not in response.content


HEADER = b"Staff Code,Person,Curr Proj %\nE1,Fictional One,10\nE2,Fictional Two,20\n"


def _upload_import(client, data=HEADER):
    upload = SimpleUploadedFile("r.csv", data)
    client.post("/imports/", {"file": upload, "source_system": "HR"})
    return ImportBatch.objects.get()


def test_admin_corrects_a_mapping_the_file_did_not_guess(org):
    """AC-IMPORT-04"""
    client = client_for(make_user(org, Role.ADMIN))
    batch = _upload_import(client)
    assert batch.rows.count() == 0
    page = client.get(f"/imports/{batch.pk}/").content.decode()
    assert "Staff Code" in page
    assert "Confirm these counts" not in page
    assert client.post(f"/imports/{batch.pk}/confirm/", follow=True).status_code == 200
    assert not TalentProfile.objects.for_org(org).exists()
    client.post(
        f"/imports/{batch.pk}/mapping/",
        {"map_0": "external_id", "map_1": "display_name", "map_2": "allocation_pct"},
    )
    batch.refresh_from_db()
    assert batch.mapping_version == 2
    assert batch.rows.count() == 2
    assert "Confirm these counts" in client.get(f"/imports/{batch.pk}/").content.decode()
    client.post(f"/imports/{batch.pk}/confirm/")
    batch.refresh_from_db()
    assert batch.insert_count == 2
    assert batch.source_rows == []
    assert TalentProfile.objects.get(external_id="E2").allocation_pct == 20


@pytest.mark.parametrize(
    "mapping",
    [
        {"map_0": "external_id", "map_1": "external_id", "map_2": ""},
        {"map_0": "external_id", "map_1": "", "map_2": ""},
        {"map_0": "not_a_field", "map_1": "display_name", "map_2": ""},
    ],
    ids=["same-field-twice", "no-name-column", "unknown-field"],
)
def test_bad_mappings_are_refused(org, mapping):
    """AC-IMPORT-06"""
    client = client_for(make_user(org, Role.ADMIN))
    batch = _upload_import(client)
    client.post(f"/imports/{batch.pk}/mapping/", mapping)
    batch.refresh_from_db()
    assert batch.mapping_version == 1
    assert batch.rows.count() == 0


def test_staff_see_and_resolve_data_requests(org, client):
    """AC-CAND-18"""
    profile = make_profile(org, name="Asking Person")
    record = DataRequest.objects.create(organisation=org, profile=profile, kind="DELETION")
    page = client.get("/requests/").content.decode()
    assert "Asking Person" in page
    assert "Deletion" in page
    client.post(f"/profiles/{profile.pk}/requests/resolve/")
    record.refresh_from_db()
    assert record.resolved_at is not None
    assert "Nothing is waiting" in client.get("/requests/").content.decode()
    profile.refresh_from_db()
    assert profile.archived_at is None


def test_other_organisations_requests_do_not_appear(org, client):
    """AC-AUTH-13"""
    other = make_org()
    profile = make_profile(other, name="Other Person")
    DataRequest.objects.create(organisation=other, profile=profile, kind="DELETION")
    assert "Other Person" not in client.get("/requests/").content.decode()


def test_profiles_search_and_pagination(org, client):
    """AC-DASH-08"""
    for number in range(30):
        make_profile(org, name=f"Person {number:02d}")
    make_profile(org, name="Unique Needle")
    first = client.get("/profiles/").content.decode()
    assert "Person 00" in first
    assert "Person 29" not in first
    assert "page=2" in first
    assert "Person 29" in client.get("/profiles/?page=2").content.decode()
    found = client.get("/profiles/?q=needle").content.decode()
    assert "Unique Needle" in found
    assert "Person 00" not in found
    assert "No profiles match" in client.get("/profiles/?q=nothing-like-this").content.decode()
    assert client.get("/profiles/?page=junk").status_code == 200


def _run_with(org, staff, *names):
    project = make_project(org, approver=staff)
    for name in names:
        make_profile(org, name=name)
    run, _created = create_run(project, f"k-{project.pk}", {}, staff, org)
    return run


def test_shortlist_search_paginates_and_reconciles_with_the_export(org, client, staff):
    """AC-DASH-13"""
    names = [f"Person {number:02d}" for number in range(30)]
    run = _run_with(org, staff, *names, "Unique Needle")
    first = client.get(f"/runs/{run.pk}/").content.decode()
    assert first.count('class="candidate-link"') == 25
    assert "page=2" in first
    found = client.get(f"/runs/{run.pk}/?q=needle").content.decode()
    assert found.count('class="candidate-link"') == 1
    export = client.get(f"/api/runs/{run.pk}/export.csv?q=needle").content.decode()
    assert len(export.strip().splitlines()) - 1 == 1
    assert client.get(f"/api/runs/{run.pk}/dashboard/?q=needle").json()["total"] == 1


def test_shortlist_names_the_blocking_must_have_and_the_next_action(org, client, staff):
    """AC-RANK-14"""
    project = make_project(org, approver=staff)
    profile = make_profile(org, name="Has A File")
    upload_fixture("demo_candidate_a", profile)
    run, _created = create_run(project, "k", {}, staff, org)
    page = client.get(f"/runs/{run.pk}/").content.decode()
    assert "Needs: ENOVIA configuration (Provisional), Migration validation (Unknown)" in page
    assert "Review evidence" in page
    assert f"/profiles/{profile.pk}/#evidence" in page


def test_only_with_evidence_hides_empty_candidates_and_reconciles(org, client, staff):
    """AC-DASH-13"""
    from apps.talent.services import add_form_claim

    run_project = make_project(org, approver=staff)
    claimed = make_profile(org, name="Has Claim")
    add_form_claim(claimed, "Migration validation")
    make_profile(org, name="Has Nothing")
    run, _created = create_run(run_project, "k", {}, staff, org)
    page = client.get(f"/runs/{run.pk}/?evidence=1").content.decode()
    assert "Has Claim" in page
    assert "Has Nothing" not in page
    export = client.get(f"/api/runs/{run.pk}/export.csv?evidence=1").content.decode()
    assert "Has Nothing" not in export


def test_dashboard_lists_the_work_waiting_for_a_person(org, client):
    """AC-DASH-01"""
    profile = make_profile(org)
    upload_fixture("demo_candidate_a", profile)
    DataRequest.objects.create(organisation=org, profile=profile, kind="CORRECTION")
    page = client.get("/dashboard/").content.decode()
    assert "passages waiting for review" in page
    assert "1 data request<" in page


def test_score_explanation_is_on_the_shortlist(org, client, staff):
    """AC-DASH-04"""
    run = _run_with(org, staff, "Anyone")
    page = client.get(f"/runs/{run.pk}/").content.decode()
    assert "How to read these two numbers" in page
