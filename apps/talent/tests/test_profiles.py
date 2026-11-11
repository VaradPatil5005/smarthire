import pytest
from django.db import IntegrityError, transaction

from apps.matching.vocabulary import load_seed_pack
from apps.talent.models import DataRequest, SkillClaim, TalentProfile
from apps.tenancy.models import Role
from tests.factories.world import (
    client_for,
    make_org,
    make_profile,
    make_user,
    upload_fixture,
)

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture(autouse=True)
def vocabulary():
    load_seed_pack()


@pytest.fixture
def org():
    return make_org()


@pytest.fixture
def candidate(org):
    return make_user(org, Role.CANDIDATE)


def _register(client, **extra):
    return client.post(
        "/api/profiles/me/", {"display_name": "New Person", "title": "Engineer", **extra}, JSON
    )


def test_candidate_registers_external_in_own_org_ignoring_payload(org, candidate):
    """AC-CAND-01"""
    other = make_org()
    client = client_for(candidate)
    response = _register(client, organisation=str(other.pk), role="ADMIN", resource_type="INTERNAL")
    assert response.status_code == 201
    profile = TalentProfile.objects.get(owner=candidate)
    assert profile.organisation == org
    assert profile.resource_type == "EXTERNAL"


def test_staff_saves_internal_profile_with_bench_fields(org):
    """AC-CAND-02"""
    client = client_for(make_user(org))
    response = client.post(
        "/api/profiles/",
        {
            "display_name": "Bench",
            "title": "Architect",
            "resource_type": "INTERNAL",
            "allocation_pct": 40,
            "available_from": "2026-12-01",
        },
        JSON,
    )
    assert response.status_code == 201
    assert response.json()["allocation_pct"] == 40
    assert response.json()["available_from"] == "2026-12-01"


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"display_name": "X"}, "title"),
        (
            {
                "display_name": "X",
                "title": "T",
                "resource_type": "INTERNAL",
                "available_from": "2026-12-01",
            },
            "allocation_pct",
        ),
        (
            {"display_name": "X", "title": "T", "resource_type": "INTERNAL", "allocation_pct": 10},
            "available_from",
        ),
    ],
)
def test_missing_fields_are_named_and_nothing_is_saved(org, payload, field):
    """AC-CAND-03"""
    client = client_for(make_user(org))
    response = client.post("/api/profiles/", payload, JSON)
    assert response.status_code == 400
    assert field in response.json()
    assert TalentProfile.objects.count() == 0


@pytest.mark.parametrize("allocation", [-1, 101])
def test_allocation_out_of_range_is_rejected(org, allocation):
    """AC-CAND-04"""
    client = client_for(make_user(org))
    response = client.post(
        "/api/profiles/",
        {
            "display_name": "X",
            "title": "T",
            "resource_type": "INTERNAL",
            "allocation_pct": allocation,
            "available_from": "2026-12-01",
        },
        JSON,
    )
    assert response.status_code == 400


def test_allocation_over_100_is_rejected_by_the_database(org):
    """AC-CAND-04"""
    with pytest.raises(IntegrityError), transaction.atomic():
        make_profile(org, allocation_pct=101)


def test_manual_skill_is_a_structured_form_claim(org, candidate):
    """AC-CAND-05"""
    client = client_for(candidate)
    _register(client)
    response = client.post("/api/profiles/me/claims/", {"skill": "3DX", "months": 12}, JSON)
    assert response.status_code == 201
    claim = SkillClaim.objects.get()
    assert claim.provenance == "FORM"
    assert claim.skill.canonical_name == "3DEXPERIENCE"
    assert b"Self-reported" in client.get("/me/").content


def test_repeat_claim_directly_or_by_alias_leaves_one(org, candidate):
    """AC-CAND-06"""
    client = client_for(candidate)
    _register(client)
    for skill in ("3DEXPERIENCE", "3DX", "3dx"):
        assert client.post("/api/profiles/me/claims/", {"skill": skill}, JSON).status_code == 201
    assert SkillClaim.objects.count() == 1


def test_me_returns_profile_claims_uploads_and_correction_route(org, candidate):
    """AC-CAND-11"""
    client = client_for(candidate)
    _register(client)
    body = client.get("/api/profiles/me/").json()
    assert body["display_name"] == "New Person"
    assert body["claims"] == []
    assert body["uploads"] == []
    assert set(body["correction_route"]) >= {"edit_profile", "add_skill", "upload_new_version"}


def test_flagged_and_clean_files_look_identical_to_the_candidate(org, candidate):
    """AC-CAND-11, AC-UPLOAD-28 (F-18)"""
    client = client_for(candidate)
    _register(client)
    profile = TalentProfile.objects.get(owner=candidate)
    upload_fixture("atk_01_white_on_white_keywords", profile, candidate)
    upload_fixture("cln_01_white_on_white_keywords", profile, candidate)
    uploads = client.get("/api/profiles/me/").json()["uploads"]
    assert {u["status"] for u in uploads} == {"PROCESSED"}
    assert "LOW_CONTRAST" not in client.get("/me/").content.decode()


def test_candidate_with_flagged_file_can_still_correct_profile(org, candidate):
    """AC-CAND-12"""
    client = client_for(candidate)
    _register(client)
    profile = TalentProfile.objects.get(owner=candidate)
    upload_fixture("atk_01_white_on_white_keywords", profile, candidate)
    assert client.patch("/api/profiles/me/", {"title": "Changed"}, JSON).status_code == 200
    assert client.post("/api/profiles/me/claims/", {"skill": "MQL"}, JSON).status_code == 201


def test_notice_period_value_and_unknown_are_stored(org, candidate):
    """AC-CAND-14"""
    client = client_for(candidate)
    _register(client, notice_days=45)
    assert TalentProfile.objects.get(owner=candidate).notice_days == 45
    other = make_user(org, Role.CANDIDATE)
    _register(client_for(other))
    assert TalentProfile.objects.get(owner=other).notice_days is None


def test_source_key_unique_within_org_only(org):
    """AC-CAND-15"""
    make_profile(org, source_system="HR", external_id="E1")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_profile(org, source_system="HR", external_id="E1")
    assert make_profile(make_org(), source_system="HR", external_id="E1").pk


def test_no_salary_field_is_requested(org, candidate):
    """AC-CAND-16"""
    client = client_for(candidate)
    _register(client)
    body = client.get("/api/profiles/me/").content.decode().lower()
    page = client.get("/me/").content.decode().lower()
    assert "ctc" not in body
    assert "salary" not in page
    field_names = {f.name for f in TalentProfile._meta.get_fields()}
    assert not field_names & {"ctc", "current_ctc", "expected_ctc", "salary"}


def test_upload_screen_shows_purpose_notice_before_the_form(org, candidate):
    """AC-CAND-17"""
    client = client_for(candidate)
    _register(client)
    page = client.get("/me/").content.decode()
    assert page.index("Before you upload") < page.index('name="file"')


def test_data_request_is_recorded_by_id(org, candidate):
    """AC-CAND-18"""
    client = client_for(candidate)
    _register(client)
    response = client.post("/api/profiles/me/data-requests/", {"kind": "DELETION"}, JSON)
    assert response.status_code == 201
    assert DataRequest.objects.get().profile.owner == candidate


def test_other_candidate_in_same_org_gets_404(org, candidate):
    """AC-AUTH-08"""
    client = client_for(candidate)
    other_profile = make_profile(org, owner=make_user(org, Role.CANDIDATE))
    assert client.get(f"/api/profiles/{other_profile.pk}/").status_code == 404


def test_candidate_reads_and_cannot_widen_own_profile(org, candidate):
    """AC-CAND-01: a candidate cannot set bench fields through the detail route."""
    client = client_for(candidate)
    _register(client)
    profile = TalentProfile.objects.get(owner=candidate)
    client.patch(
        f"/api/profiles/{profile.pk}/", {"allocation_pct": 5, "resource_type": "INTERNAL"}, JSON
    )
    profile.refresh_from_db()
    assert profile.allocation_pct is None
    assert profile.resource_type == "EXTERNAL"
