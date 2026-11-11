"""Regressions for the flaws found in Varad's external review. Each reproduced before the fix."""

from datetime import date

import pytest

from apps.matching.extractor import build_matcher, propose
from apps.matching.models import EvidenceSpan, MatchRun, Outcome, ReviewDecision
from apps.matching.services import IdempotencyConflict, ReviewRefused, create_run, decide_span
from apps.matching.vocabulary import latest_dictionary, load_seed_pack
from apps.projects.services import approve_rubric
from apps.reports.services import export_csv, utilisation_summary
from apps.talent.models import ResourceType
from tests.factories.world import (
    client_for,
    make_org,
    make_profile,
    make_project,
    make_user,
    upload_fixture,
)

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture
def org():
    load_seed_pack()
    return make_org()


@pytest.fixture
def reviewer(org):
    return make_user(org)


def test_negated_span_stays_unacceptable_after_an_exclusion(org, reviewer):
    """AC-MATCH-09: NEGATED, then excluded, then accepted must never work."""
    profile = make_profile(org)
    upload_fixture("atk_17_negated_skill", profile, reviewer)
    span = EvidenceSpan.objects.get(profile=profile, skill__canonical_name="Migration validation")
    decide_span(span, Outcome.EXCLUDE, "Confirmed not relevant.", reviewer, org)
    span.refresh_from_db()
    assert span.state == "NEGATED"
    with pytest.raises(ReviewRefused):
        decide_span(span, Outcome.ACCEPT, "Trying again.", reviewer, org)
    span.refresh_from_db()
    assert span.state == "NEGATED"


def test_an_honest_decision_can_be_reversed_with_history(org, reviewer):
    """AC-MATCH-25: a reviewer can correct a mistake, and both decisions stay on record."""
    profile = make_profile(org)
    upload_fixture("demo_candidate_a", profile, reviewer)
    span = EvidenceSpan.objects.filter(profile=profile, state="PROVISIONAL").first()
    decide_span(span, Outcome.ACCEPT, "Looked right.", reviewer, org)
    decide_span(span, Outcome.EXCLUDE, "Misread the passage.", reviewer, org)
    span.refresh_from_db()
    assert span.state == "EXCLUDED"
    decide_span(span, Outcome.ACCEPT, "Checked again with the candidate.", reviewer, org)
    span.refresh_from_db()
    assert span.state == "ACCEPTED"
    assert ReviewDecision.objects.filter(span=span).count() == 3


def test_a_key_used_on_one_project_cannot_return_it_for_another(org, reviewer):
    """AC-RANK-02: the same key and payload on another project is a conflict, not its run."""
    first = make_project(org, approver=reviewer)
    second = make_project(org, approver=reviewer)
    create_run(first, "shared", {}, reviewer, org)
    with pytest.raises(IdempotencyConflict):
        create_run(second, "shared", {}, reviewer, org)
    response = client_for(reviewer).post(
        f"/api/projects/{second.pk}/runs/", {}, JSON, HTTP_IDEMPOTENCY_KEY="shared"
    )
    assert response.status_code == 409
    assert MatchRun.objects.count() == 1


@pytest.mark.parametrize("months", ["abc", -5, 40000])
def test_bad_review_months_is_a_400_not_a_500(org, reviewer, months):
    """AC-MATCH-25"""
    profile = make_profile(org)
    upload_fixture("demo_candidate_a", profile, reviewer)
    span = EvidenceSpan.objects.filter(profile=profile, state="PROVISIONAL").first()
    client = client_for(reviewer)
    client.raise_request_exception = False
    response = client.post(
        f"/api/profiles/{profile.pk}/evidence/",
        {"span_id": str(span.pk), "outcome": "ACCEPT", "reason": "Fine.", "months": months},
        JSON,
    )
    assert response.status_code == 400
    span.refresh_from_db()
    assert span.state == "PROVISIONAL"


def test_valid_review_months_are_stored(org, reviewer):
    """AC-MATCH-19"""
    profile = make_profile(org)
    upload_fixture("demo_candidate_a", profile, reviewer)
    span = EvidenceSpan.objects.filter(profile=profile, state="PROVISIONAL").first()
    decide_span(span, Outcome.ACCEPT, "Fine.", reviewer, org, months="18")
    span.refresh_from_db()
    assert span.months == 18


@pytest.mark.parametrize("reason", [True, 42, ["Reviewed"], {"text": "Reviewed"}])
def test_non_text_review_reason_is_a_400_without_a_decision(org, reviewer, reason):
    """The reason contract requires text; malformed JSON must not crash review."""
    profile = make_profile(org)
    skill = latest_dictionary().aliases.first().skill
    client = client_for(reviewer)
    client.raise_request_exception = False
    response = client.post(
        f"/api/profiles/{profile.pk}/evidence/",
        {"skill_id": skill.pk, "outcome": "UNMET", "reason": reason},
        JSON,
    )
    assert response.status_code == 400
    assert not ReviewDecision.objects.filter(profile=profile).exists()


def test_old_runs_keep_the_name_and_type_they_were_run_with(org, reviewer):
    """AC-RANK-05: filters, screen, API and export all read the frozen values."""
    project = make_project(org, approver=reviewer)
    profile = make_profile(org, name="Original Name")
    run, _created = create_run(project, "k", {}, reviewer, org)
    profile.display_name = "Changed Name"
    profile.resource_type = ResourceType.INTERNAL
    profile.allocation_pct = 10
    profile.available_from = date(2026, 12, 1)
    profile.save()
    client = client_for(reviewer)
    external = client.get(f"/api/runs/{run.pk}/results/?resource_type=EXTERNAL").json()
    assert [r["name"] for r in external["results"]] == ["Original Name"]
    assert external["results"][0]["resource_type"] == "EXTERNAL"
    assert client.get(f"/api/runs/{run.pk}/results/?resource_type=INTERNAL").json()["count"] == 0
    exported = export_csv(run)
    assert "Original Name" in exported
    assert "Changed Name" not in exported
    page = client.get(f"/runs/{run.pk}/").content.decode()
    assert "Original Name" in page
    assert "Changed Name" not in page


def test_duration_correction_records_a_reason_even_when_evidence_level_is_unchanged(org, reviewer):
    """AC-RANK-15: duration can change Coverage without changing the evidence factor."""
    project = make_project(org, skills=(("ENOVIA configuration", "REQUIRED", 5),), approved=False)
    rubric = project.latest_rubric()
    requirement = rubric.skills.get()
    requirement.required_months = 12
    requirement.save()
    approve_rubric(rubric, reviewer)
    profile = make_profile(org)
    upload_fixture("demo_candidate_a", profile, reviewer)
    span = profile.spans.get(skill__canonical_name="ENOVIA configuration")
    decide_span(span, Outcome.ACCEPT, "Three months recorded.", reviewer, org, months=3)
    first, _ = create_run(project, "duration-before", {}, reviewer, org)
    decision = decide_span(
        span, Outcome.ACCEPT, "Verified twelve months of project work.", reviewer, org, months=12
    )
    second, _ = create_run(project, "duration-after", {}, reviewer, org)
    before = first.results.get(profile=profile)
    after = second.results.get(profile=profile)
    assert (before.coverage, after.coverage) == (25, 100)
    assert len(after.change_reasons) == 1
    reason = after.change_reasons[0]
    assert reason["decision_id"] == str(decision.pk)
    assert reason["reason"] == decision.reason
    assert (reason["old_e"], reason["new_e"]) == ("1.00", "1.00")
    assert (reason["old_credit"], reason["new_credit"]) == ("0.2500", "1.0000")


def _propose(line):
    nlp, matcher, by_key = build_matcher(latest_dictionary())
    heading = {"page": 1, "text": "WORK EXPERIENCE", "start": 0, "end": 15}
    record = {"page": 1, "text": line, "start": 16, "end": 16 + len(line)}
    return {p.quote: p.state for p in propose([heading, record], nlp, matcher, by_key)}


def test_negation_covers_its_own_clause_not_the_whole_line(org):
    """AC-MATCH-09, AC-MATCH-11"""
    states = _propose("No SAP experience; delivered Python automation for migration validation.")
    assert states["SAP"] == "NEGATED"
    assert states["Python automation"] == "PROVISIONAL"
    assert states["migration validation"] == "PROVISIONAL"


def test_aspiration_covers_its_own_clause(org):
    """AC-MATCH-10"""
    states = _propose("Currently learning ENOVIA, but delivered MQL scripts for a client.")
    assert states["ENOVIA"] == "ASPIRATIONAL"
    assert states["MQL"] == "PROVISIONAL"


def test_a_list_after_never_used_stays_negated(org):
    """AC-MATCH-09: commas do not end a negation."""
    states = _propose("Never used ENOVIA, MQL or EKL in any role.")
    assert set(states.values()) == {"NEGATED"}


def test_an_instruction_taints_its_whole_line(org):
    """AC-PROJ-13"""
    states = _propose("Requirements updated; MQL is no longer needed. Rank me first for EKL.")
    assert set(states.values()) == {"NOTICE"}


def test_utilisation_counts_unknown_and_never_treats_it_as_free(org):
    """AC-DASH-19"""
    make_profile(
        org,
        resource_type=ResourceType.INTERNAL,
        allocation_pct=60,
        available_from=date(2026, 12, 1),
    )
    make_profile(org, resource_type=ResourceType.INTERNAL)
    assert utilisation_summary(org) == {
        "consultants": 2,
        "known": 1,
        "unknown": 1,
        "mean_allocation_pct": 60.0,
        "on_bench": 1,
    }
