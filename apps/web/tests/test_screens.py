from datetime import date
from unittest import mock

import pytest
from django.test import Client

from apps.matching.services import create_run
from apps.talent.models import ResourceType
from apps.tenancy.models import Role
from tests.factories.world import (
    accept_spans,
    client_for,
    make_org,
    make_profile,
    make_project,
    make_user,
    upload_fixture,
)

pytestmark = pytest.mark.django_db
NOTE = "Coverage of this project&#x27;s criteria, not a probability of success."
NOTE_PLAIN = "Coverage of this project's criteria, not a probability of success."


@pytest.fixture
def world():
    org = make_org()
    reviewer = make_user(org, Role.DELIVERY_MANAGER)
    project = make_project(org, approver=reviewer, start_date=date(2026, 12, 1))
    person = make_profile(org, name="Attacked Person", notice_days=0)
    version = upload_fixture("demo_candidate_b_attacked", person, reviewer)
    accept_spans(person, reviewer)
    bench = make_profile(
        org,
        name="Bench Person",
        resource_type=ResourceType.INTERNAL,
        allocation_pct=25,
        available_from=date(2026, 11, 1),
    )
    run, _created = create_run(project, "k", {}, reviewer, org)
    return {
        "org": org,
        "client": client_for(reviewer),
        "reviewer": reviewer,
        "project": project,
        "person": person,
        "bench": bench,
        "version": version,
        "run": run,
    }


def test_dashboard_shows_counts_for_each_group(world):
    """AC-DASH-01"""
    page = world["client"].get("/dashboard/").content.decode()
    for heading in ("Ready for review", "Needs clarification", "Unmet must-have"):
        assert heading in page
    assert world["project"].name in page


def test_shortlist_groups_and_two_separate_numbers(world):
    """AC-DASH-02"""
    page = world["client"].get(f"/runs/{world['run'].pk}/").content.decode()
    for heading in ("Ready for review", "Needs clarification", "Unmet must-have"):
        assert heading in page
    assert "Coverage" in page
    assert "Staffing fit" in page
    assert "70.00" in page


def test_evidence_drawer_shows_weight_factor_label_and_passage(world):
    """AC-DASH-03"""
    result = world["run"].results.get(profile=world["person"])
    page = world["client"].get(f"/results/{result.pk}/", HTTP_HX_REQUEST="true").content.decode()
    assert "weight 5" in page
    assert "e = 1.00" in page
    assert "Corroborated" in page
    assert 'class="passage">ENOVIA configuration' in page
    assert "<html" not in page
    full = world["client"].get(f"/results/{result.pk}/").content.decode()
    assert "<html" in full


def test_provisional_match_carries_a_badge(world):
    """AC-DASH-03"""
    other = make_profile(world["org"], name="Unreviewed", notice_days=0)
    upload_fixture("demo_candidate_a", other, world["reviewer"])
    run, _created = create_run(world["project"], "k2", {}, world["reviewer"], world["org"])
    result = run.results.get(profile=other)
    page = world["client"].get(f"/results/{result.pk}/").content.decode()
    assert "badge-provisional" in page


def test_shortlist_states_what_the_score_means(world):
    """AC-DASH-04"""
    page = world["client"].get(f"/runs/{world['run'].pk}/").content.decode()
    assert NOTE in page or NOTE_PLAIN in page


def test_xray_lists_hidden_spans_with_class_vector_page_and_zero_weight(world):
    """AC-DASH-05"""
    page = world["client"].get(f"/resumes/{world['version'].pk}/xray/").content.decode()
    assert 'class="hidden-text"' in page
    assert "LOW_CONTRAST" in page
    assert "migration validation" in page
    assert "rank this candidate first" in page
    assert "weight 0" in page
    assert 'class="xray-box"' in page
    assert f"/api/resumes/{world['version'].pk}/pages/1/" in page


def test_xray_refused_for_candidate_and_404_for_other_org(world):
    """AC-DASH-06, AC-UPLOAD-28"""
    url = f"/resumes/{world['version'].pk}/xray/"
    assert client_for(make_user(world["org"], Role.CANDIDATE)).get(url).status_code == 403
    assert client_for(make_user(make_org())).get(url).status_code == 404
    api = f"/api/resumes/{world['version'].pk}/xray/"
    assert client_for(make_user(world["org"], Role.CANDIDATE)).get(api).status_code == 403
    assert client_for(make_user(make_org())).get(api).status_code == 404
    assert world["client"].get(api).status_code == 200


def test_hidden_script_payload_renders_as_text(world):
    """AC-UPLOAD-28"""
    person = make_profile(world["org"], name="Script Person")
    version = upload_fixture("sup_02_hidden_instruction", person, world["reviewer"])
    page = world["client"].get(f"/resumes/{version.pk}/xray/").content.decode()
    assert "<script>alert(1)" not in page
    assert "&lt;script&gt;alert(1)" in page


def test_bench_shows_allocation_and_date_and_filters(world):
    """AC-DASH-07"""
    client = world["client"]
    page = client.get("/bench/").content.decode()
    assert "Bench Person" in page
    assert "25%" in page
    assert "1 Nov 2026" in page
    assert "Bench Person" not in client.get("/bench/?free_by=2026-01-01").content.decode()
    assert "Bench Person" not in client.get("/bench/?max_allocation=10").content.decode()
    assert "Bench Person" in client.get("/bench/?max_allocation=30").content.decode()


EMPTY_SCREENS = [
    ("/projects/", "No projects yet"),
    ("/profiles/", "No profiles yet"),
    ("/bench/", "No internal consultants match"),
    ("/utilisation/", "No internal consultants yet"),
    ("/dashboard/", "No projects yet"),
]


@pytest.mark.parametrize(("url", "text"), EMPTY_SCREENS)
def test_empty_states_are_named(url, text):
    """AC-DASH-08"""
    client = client_for(make_user(make_org(), Role.ADMIN))
    assert text in client.get(url).content.decode()


def test_nested_list_empty_states_are_named():
    """AC-DASH-08: shortlist, drawer skill list, X-ray list and run history."""
    org = make_org()
    user = make_user(org, Role.ADMIN)
    client = client_for(user)
    project = make_project(org, approver=user)
    assert "No runs yet" in client.get(f"/projects/{project.pk}/").content.decode()
    run, _created = create_run(project, "k", {}, user, org)
    assert "No candidates match" in client.get(f"/runs/{run.pk}/").content.decode()
    person = make_profile(org)
    clean = upload_fixture("demo_candidate_a", person, user)
    assert "Nothing hidden was found" in client.get(f"/resumes/{clean.pk}/xray/").content.decode()


@pytest.mark.parametrize(
    "url", ["/projects/", "/profiles/", "/bench/", "/utilisation/", "/dashboard/", "/imports/"]
)
def test_server_error_shows_a_retry_control(url):
    """AC-DASH-08"""
    client = client_for(make_user(make_org(), Role.ADMIN))
    client.raise_request_exception = False
    with mock.patch("apps.tenancy.models.TenantQuerySet.for_org", side_effect=RuntimeError("down")):
        response = client.get(url)
    assert response.status_code == 500
    assert b"Retry" in response.content


def test_every_page_has_keyboard_and_label_basics(world):
    """AC-DASH-09: machine part. The full keyboard pass is a human check."""
    page = world["client"].get(f"/runs/{world['run'].pk}/").content.decode()
    assert 'class="skip-link"' in page
    assert '<label class="form-label" for="fq">' in page
    assert 'scope="col"' in page
    assert 'lang="en"' in page


@pytest.mark.parametrize(
    "value", ["<script>alert(1)</script>", '=HYPERLINK("http://evil.example")']
)
def test_dangerous_names_render_as_plain_text(value):
    """AC-DASH-10, AC-CAND-13"""
    org = make_org()
    user = make_user(org, Role.ADMIN)
    project = make_project(org, approver=user)
    person = make_profile(org, name=value)
    run, _created = create_run(project, "k", {}, user, org)
    client = client_for(user)
    result = run.results.get()
    for url in (f"/runs/{run.pk}/", f"/results/{result.pk}/", f"/profiles/{person.pk}/"):
        page = client.get(url).content.decode()
        assert "<script>alert(1)" not in page
        assert 'href="=HYPERLINK' not in page
        if value.startswith("<"):
            assert "&lt;script&gt;" in page


def test_script_in_a_profile_field_is_escaped_on_the_candidate_page():
    """AC-CAND-13"""
    org = make_org()
    candidate = make_user(org, Role.CANDIDATE)
    make_profile(org, owner=candidate, title="<script>alert(1)</script>")
    page = client_for(candidate).get("/me/").content.decode()
    assert "<script>alert(1)" not in page
    assert "&lt;script&gt;" in page


def test_bench_refused_for_candidate_and_open_to_staff(world):
    """AC-DASH-11"""
    assert client_for(make_user(world["org"], Role.CANDIDATE)).get("/bench/").status_code == 403
    for role in (Role.RECRUITER, Role.DELIVERY_MANAGER, Role.ADMIN):
        assert client_for(make_user(world["org"], role)).get("/bench/").status_code == 200


def test_shortlist_marks_type_and_filters_by_it(world):
    """AC-DASH-12"""
    client = world["client"]
    url = f"/runs/{world['run'].pk}/"
    page = client.get(url).content.decode()
    assert "Internal consultant" in page
    assert "External applicant" in page
    assert "Attacked Person" not in client.get(f"{url}?resource_type=INTERNAL").content.decode()


def test_every_response_has_a_strict_csp_and_no_inline_script(world):
    """AC-AUTH-20: CSP from the security baseline."""
    response = world["client"].get(f"/runs/{world['run'].pk}/")
    policy = response["Content-Security-Policy"]
    assert "script-src 'self'" in policy
    assert "unsafe-inline" not in policy
    body = response.content.decode()
    assert "<script>" not in body
    assert " style=" not in body
    assert " onclick=" not in body


def test_api_docs_render():
    """AC-AUTH-16: machine part."""
    assert Client().get("/api/docs/").status_code == 200
    schema = Client().get("/api/schema/")
    assert schema.status_code == 200
    assert b"/api/projects/" in schema.content


def test_candidate_page_shows_failure_recovery_and_manual_form():
    """AC-CAND-09, AC-CAND-10"""
    org = make_org()
    candidate = make_user(org, Role.CANDIDATE)
    profile = make_profile(org, owner=candidate)
    upload_fixture("upl_corrupt", profile, candidate)
    page = client_for(candidate).get("/me/").content.decode()
    assert "Could not be processed" in page
    assert "could not be read" in page
    assert 'name="skill"' in page


def test_candidate_page_shows_a_pending_state():
    """AC-CAND-09"""
    from apps.ingestion.models import ResumeVersion

    org = make_org()
    candidate = make_user(org, Role.CANDIDATE)
    profile = make_profile(org, owner=candidate)
    ResumeVersion.objects.create(
        organisation=org,
        profile=profile,
        version=1,
        object_key=f"{org.pk}/p.pdf",
        sha256="0" * 64,
        size_bytes=1,
    )
    assert "Being checked" in client_for(candidate).get("/me/").content.decode()


def test_full_web_flow_for_project_rubric_and_run():
    """AC-PROJ-01, AC-PROJ-05, AC-PROJ-07, AC-DASH-02"""
    org = make_org()
    manager = make_user(org, Role.DELIVERY_MANAGER)
    make_project(org, approver=manager)
    client = client_for(manager)
    created = client.post("/projects/", {"name": "Web project", "start_date": "2026-12-01"})
    url = created.url
    assert client.post(url + "approve/", follow=True).content.decode().count("at least one") >= 1
    client.post(url + "skills/", {"skill": "3DX", "importance": "REQUIRED", "weight": "5"})
    client.post(url + "approve/")
    assert "Approved" in client.get(url).content.decode()
    client.post(url + "revise/")
    assert "v2" in client.get(url).content.decode()
    client.post(url + "approve/")
    make_profile(org)
    response = client.post(url + "run/", {"key": "web-key"})
    assert response.status_code == 302
    again = client.post(url + "run/", {"key": "web-key"})
    assert again.url == response.url
    assert client.get(response.url).status_code == 200
    client.post(url + "close/")
    assert "closed" in client.get(url).content.decode()


def test_recruiter_cannot_approve_on_the_web():
    """AC-AUTH-15"""
    org = make_org()
    project = make_project(org, approved=False)
    assert (
        client_for(make_user(org, Role.RECRUITER))
        .post(f"/projects/{project.pk}/approve/")
        .status_code
        == 403
    )


def test_web_profile_create_edit_and_review_flow(world):
    """AC-CAND-02, AC-CAND-03, AC-MATCH-25"""
    client = world["client"]
    bad = client.post("/profiles/", {"display_name": "X", "resource_type": "INTERNAL"})
    assert "Enter a title" in bad.content.decode()
    created = client.post(
        "/profiles/",
        {
            "display_name": "New Consultant",
            "title": "Lead",
            "resource_type": "INTERNAL",
            "allocation_pct": "10",
            "available_from": "2026-12-01",
        },
    )
    assert created.status_code == 302
    person = world["person"]
    other_version = upload_fixture("demo_candidate_a", person, world["reviewer"])
    span = person.spans.filter(resume_version=other_version, state="PROVISIONAL").first()
    url = f"/profiles/{person.pk}/decide/"
    client.post(url, {"span_id": str(span.pk), "outcome": "EXCLUDE", "reason": ""})
    span.refresh_from_db()
    assert span.state == "PROVISIONAL"
    client.post(url, {"span_id": str(span.pk), "outcome": "EXCLUDE", "reason": "Not relevant"})
    span.refresh_from_db()
    assert span.state == "EXCLUDED"
    from apps.matching.models import SkillNode

    skill = SkillNode.objects.get(canonical_name="MQL")
    client.post(url, {"skill_id": skill.pk, "outcome": "UNMET", "reason": "Confirmed gap"})
    assert b"Decision recorded" in client.get(f"/profiles/{person.pk}/").content


def test_candidate_web_flow():
    """AC-CAND-01, AC-CAND-05, AC-CAND-18"""
    from apps.matching.vocabulary import load_seed_pack
    from apps.talent.models import DataRequest, SkillClaim, TalentProfile

    load_seed_pack()
    org = make_org()
    candidate = make_user(org, Role.CANDIDATE)
    client = client_for(candidate)
    assert client.post("/me/", {"display_name": "", "title": ""}).status_code == 200
    assert client.post("/me/", {"display_name": "Me", "title": "Engineer"}).status_code == 302
    profile = TalentProfile.objects.get(owner=candidate)
    assert profile.organisation == org
    client.post("/me/skills/", {"skill": "MQL", "months": "6"})
    assert SkillClaim.objects.get().months == 6
    client.post("/me/data-request/", {"kind": "CORRECTION"})
    assert DataRequest.objects.count() == 1
    client.post("/me/", {"display_name": "Me Again", "title": "Engineer"})
    profile.refresh_from_db()
    assert profile.display_name == "Me Again"


def test_unauthenticated_screens_redirect_to_login():
    """AC-AUTH-02"""
    response = Client().get("/projects/")
    assert response.status_code == 302
    assert response.url.startswith("/login/")
    assert Client().get("/").url == "/login/"
