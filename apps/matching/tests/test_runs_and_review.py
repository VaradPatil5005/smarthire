import socket
import threading
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.core import mail
from django.db import connection

from apps.matching.models import EvidenceSpan, MatchRun, Outcome, ReviewDecision, SkillNode
from apps.matching.services import (
    ReviewRefused,
    RunRefused,
    create_run,
    decide_span,
    record_skill_decision,
    reproduce_run,
)
from apps.projects.services import add_skill, next_version
from apps.talent.services import add_form_claim
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
JSON = "application/json"
RUN_DATE = date(2026, 11, 8)


@pytest.fixture
def org():
    return make_org()


@pytest.fixture
def reviewer(org):
    return make_user(org)


@pytest.fixture
def project(org, reviewer):
    return make_project(org, approver=reviewer, start_date=RUN_DATE + timedelta(days=30))


def _run(project, reviewer, key="k1", **payload):
    run, _created = create_run(project, key, payload, reviewer, project.organisation)
    return run


def _candidate_a(org, reviewer):
    profile = make_profile(org, name="Candidate A", notice_days=0)
    upload_fixture("demo_candidate_a", profile, reviewer)
    accept_spans(profile, reviewer, ["ENOVIA configuration"])
    add_form_claim(profile, "Migration validation")
    return profile


def _candidate_b(org, reviewer, fixture="demo_candidate_b"):
    profile = make_profile(org, name="Candidate B", notice_days=0)
    upload_fixture(fixture, profile, reviewer)
    accept_spans(profile, reviewer, ["ENOVIA configuration", "Python automation"])
    return profile


def test_worked_example_through_the_whole_pipeline(org, reviewer, project):
    """AC-MATCH-15, AC-MATCH-16, AC-MATCH-18, AC-RANK-15"""
    candidate_a = _candidate_a(org, reviewer)
    candidate_b = _candidate_b(org, reviewer)
    first = _run(project, reviewer)
    a_result = first.results.get(profile=candidate_a)
    b_result = first.results.get(profile=candidate_b)
    assert (a_result.coverage, a_result.review_group) == (Decimal("65.00"), "NEEDS_CLARIFICATION")
    assert (b_result.coverage, b_result.review_group) == (Decimal("70.00"), "NEEDS_CLARIFICATION")

    upload_fixture("demo_candidate_b_corrected", candidate_b, reviewer)
    span = EvidenceSpan.objects.get(
        profile=candidate_b, skill__canonical_name="Migration validation"
    )
    decision = decide_span(span, Outcome.ACCEPT, "Matches the migration work.", reviewer, org)
    second = _run(project, reviewer, key="k2")
    new_b = second.results.get(profile=candidate_b)
    assert (new_b.coverage, new_b.review_group) == (Decimal("100.00"), "READY")

    b_result.refresh_from_db()
    assert b_result.coverage == Decimal("70.00")
    reason = new_b.change_reasons[0]
    assert reason["decision_id"] == str(decision.pk)
    assert reason["skill"] == "Migration validation"
    assert (reason["old_e"], reason["new_e"]) == ("0.00", "1.00")
    assert reason["reason"] == "Matches the migration work."


def test_run_records_pinned_versions_and_inputs(org, reviewer, project):
    """AC-RANK-01"""
    make_profile(org)
    run = _run(project, reviewer, run_date="2026-11-08")
    assert run.rubric_version == project.latest_rubric()
    assert run.dictionary_version.number == 1
    assert run.algorithm_version == "1.1"
    assert run.run_date == RUN_DATE
    assert run.results.first().inputs["availability"]["resource_type"] == "EXTERNAL"


def test_idempotency_key_same_payload_same_run_different_payload_409(org, reviewer, project):
    """AC-RANK-02"""
    client = client_for(reviewer)
    url = f"/api/projects/{project.pk}/runs/"
    first = client.post(url, {}, JSON, HTTP_IDEMPOTENCY_KEY="abc")
    again = client.post(url, {}, JSON, HTTP_IDEMPOTENCY_KEY="abc")
    assert first.status_code == 201
    assert again.status_code == 200
    assert first.json()["id"] == again.json()["id"]
    assert MatchRun.objects.count() == 1
    conflict = client.post(url, {"run_date": "2026-01-01"}, JSON, HTTP_IDEMPOTENCY_KEY="abc")
    assert conflict.status_code == 409


def test_same_key_in_another_org_makes_its_own_run(org, reviewer, project):
    """AC-RANK-03"""
    other_org = make_org()
    other_user = make_user(other_org)
    other_project = make_project(other_org, approver=other_user)
    assert (
        _run(project, reviewer, key="shared").pk != _run(other_project, other_user, key="shared").pk
    )


def test_rerun_is_identical(org, reviewer, project):
    """AC-RANK-04"""
    _candidate_a(org, reviewer)
    _candidate_b(org, reviewer)
    make_profile(org, name="Nobody")
    run = _run(project, reviewer)
    for _ in range(3):
        assert reproduce_run(run)["identical"] is True


def test_old_run_survives_later_changes_and_still_reproduces(org, reviewer, project):
    """AC-RANK-05"""
    candidate = _candidate_a(org, reviewer)
    run = _run(project, reviewer)
    before = run.results.get(profile=candidate).coverage
    add_form_claim(candidate, "Python automation")
    candidate.notice_days = 999
    candidate.save()
    draft = next_version(project)
    add_skill(draft, "MQL", "REQUIRED", 9)
    assert run.results.get(profile=candidate).coverage == before
    assert reproduce_run(run)["identical"] is True


def test_reproduction_uses_the_stored_run_date(org, reviewer, project):
    """AC-RANK-06"""
    make_profile(org, notice_days=30)
    run = _run(project, reviewer, run_date=RUN_DATE.isoformat())
    with mock.patch("apps.matching.scoring.date") as fake:
        fake.fromordinal = date.fromordinal
        fake.today.return_value = date(2030, 1, 1)
        assert reproduce_run(run)["identical"] is True


def test_failed_run_leaves_the_last_shortlist(org, reviewer, project):
    """AC-RANK-07"""
    make_profile(org)
    good = _run(project, reviewer)
    with (
        mock.patch("apps.matching.services.score_from_inputs", side_effect=RuntimeError("boom")),
        pytest.raises(RuntimeError),
    ):
        _run(project, reviewer, key="k2")
    assert list(MatchRun.objects.filter(project=project)) == [good]
    assert good.results.count() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="Needs real concurrency")
def test_two_simultaneous_requests_with_one_key_make_one_run():
    """AC-RANK-08"""
    from apps.matching.vocabulary import load_seed_pack

    load_seed_pack()
    org = make_org()
    user = make_user(org)
    project = make_project(org, approver=user)
    make_profile(org)
    barrier = threading.Barrier(2)
    found = []

    def worker():
        try:
            barrier.wait(timeout=10)
            run, _created = create_run(project, "same", {}, user, org)
            found.append(run.pk)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(found) == 2
    assert found[0] == found[1]
    assert MatchRun.objects.filter(project=project).count() == 1


def test_flag_changes_nothing_about_the_score(org, reviewer, project):
    """AC-RANK-10"""
    honest = _candidate_b(org, reviewer)
    flagged = _candidate_b(org, reviewer, "demo_candidate_b_attacked")
    assert flagged.resumes.get().status == "FLAGGED"
    run = _run(project, reviewer)
    one = run.results.get(profile=honest)
    two = run.results.get(profile=flagged)
    assert (one.coverage, one.review_group) == (two.coverage, two.review_group)


def test_parse_failure_is_shown_with_a_reason_and_scores_as_no_upload(org, reviewer, project):
    """AC-RANK-11, AC-CAND-10"""
    broken = make_profile(org, name="Broken File")
    no_upload = make_profile(org, name="No Upload")
    upload_fixture("upl_corrupt", broken, reviewer)
    run = _run(project, reviewer)
    result = run.results.get(profile=broken)
    assert result.review_group == "NEEDS_CLARIFICATION"
    assert "could not be read" in result.group_reason
    assert result.coverage == run.results.get(profile=no_upload).coverage


def test_fully_scanned_file_routes_to_manual_and_scores_as_no_upload(org, reviewer, project):
    """AC-UPLOAD-20, AC-CAND-10"""
    scanned = make_profile(org, name="Scanned")
    no_upload = make_profile(org, name="None")
    version = upload_fixture("ben_02_scanned_with_ocr_layer", scanned, reviewer)
    assert version.status == "CLEAN"
    assert version.visible_text == ""
    run = _run(project, reviewer)
    result = run.results.get(profile=scanned)
    assert result.coverage == run.results.get(profile=no_upload).coverage
    assert result.review_group == "NEEDS_CLARIFICATION"


def test_results_route_is_paginated_scoped_and_bucketed(org, reviewer, project):
    """AC-RANK-14"""
    _candidate_a(org, reviewer)
    make_profile(org, name="Nobody")
    run = _run(project, reviewer)
    body = client_for(reviewer).get(f"/api/runs/{run.pk}/results/?page=1").json()
    assert body["count"] == 2
    assert body["page"] == 1
    first = next(r for r in body["results"] if r["name"] == "Candidate A")
    assert [c["skill"] for c in first["matched"]] == ["ENOVIA configuration"]
    assert [c["skill"] for c in first["unresolved"]] == ["Migration validation"]
    assert [c["skill"] for c in first["missing"]] == ["Python automation"]
    assert first["matched"][0]["passage"] == "ENOVIA configuration"
    ready = client_for(reviewer).get(f"/api/runs/{run.pk}/results/?group=ready").json()
    assert ready["count"] == 0


def test_a_run_triggers_no_action_without_a_person(org, reviewer, project, monkeypatch):
    """AC-RANK-21, AC-UPLOAD-29"""
    profile = make_profile(org, name="Injected")
    upload_fixture("sup_02_hidden_instruction", profile, reviewer)
    mail.outbox.clear()

    def no_network(*args, **kwargs):
        raise AssertionError("A run opened a socket")

    with mock.patch("apps.ingestion.services.async_task") as queued:
        monkeypatch.setattr(socket, "create_connection", no_network)
        run = _run(project, reviewer)
    assert run.results.count() == 1
    assert mail.outbox == []
    queued.assert_not_called()
    profile.refresh_from_db()
    assert profile.archived_at is None


def test_accepting_text_not_in_the_visible_text_is_refused(org, reviewer):
    """AC-MATCH-24"""
    profile = make_profile(org)
    upload_fixture("demo_candidate_a", profile, reviewer)
    span = EvidenceSpan.objects.filter(profile=profile).first()
    EvidenceSpan.objects.filter(pk=span.pk).update(quote="text that is not on the page")
    span.refresh_from_db()
    with pytest.raises(ReviewRefused, match="not in the visible text"):
        decide_span(span, Outcome.ACCEPT, "Crafted.", reviewer, org)
    span.refresh_from_db()
    assert span.state == "PROVISIONAL"


def test_crafted_span_id_from_another_profile_gets_404(org, reviewer):
    """AC-MATCH-24"""
    one = make_profile(org)
    two = make_profile(org)
    upload_fixture("demo_candidate_a", one, reviewer)
    span = EvidenceSpan.objects.filter(profile=one).first()
    response = client_for(reviewer).post(
        f"/api/profiles/{two.pk}/evidence/",
        {"span_id": str(span.pk), "outcome": "ACCEPT", "reason": "Crafted."},
        JSON,
    )
    assert response.status_code == 404


def test_decision_records_actor_time_outcome_and_needs_a_reason(org, reviewer):
    """AC-MATCH-25"""
    profile = make_profile(org)
    upload_fixture("demo_candidate_a", profile, reviewer)
    span = EvidenceSpan.objects.filter(profile=profile).first()
    client = client_for(reviewer)
    url = f"/api/profiles/{profile.pk}/evidence/"
    no_reason = client.post(
        url, {"span_id": str(span.pk), "outcome": "ACCEPT", "reason": " "}, JSON
    )
    assert no_reason.status_code == 400
    assert (
        client.post(
            url, {"span_id": str(span.pk), "outcome": "EXCLUDE", "reason": "No."}, JSON
        ).status_code
        == 201
    )
    decision = ReviewDecision.objects.get()
    assert (decision.actor, decision.outcome, decision.reason) == (reviewer, "EXCLUDE", "No.")
    assert decision.created_at is not None


def test_negated_span_cannot_be_accepted(org, reviewer):
    """AC-MATCH-09"""
    profile = make_profile(org)
    upload_fixture("atk_17_negated_skill", profile, reviewer)
    span = EvidenceSpan.objects.get(profile=profile, skill__canonical_name="Migration validation")
    assert span.state == "NEGATED"
    with pytest.raises(ReviewRefused):
        decide_span(span, Outcome.ACCEPT, "Trying anyway.", reviewer, org)


def test_verified_needs_staff_method_and_reason(org, reviewer):
    """AC-MATCH-26"""
    profile = make_profile(org)
    skill = SkillNode.objects.get(canonical_name="MQL") if SkillNode.objects.exists() else None
    if skill is None:
        make_project(org)
        skill = SkillNode.objects.get(canonical_name="MQL")
    with pytest.raises(ReviewRefused):
        record_skill_decision(profile, skill, Outcome.VERIFIED, "No method", reviewer, org)
    decision = record_skill_decision(
        profile, skill, Outcome.VERIFIED, "Passed the test.", reviewer, org, "TEST"
    )
    assert decision.method == "TEST"
    candidate = make_user(org, Role.CANDIDATE)
    response = client_for(candidate).post(
        f"/api/profiles/{profile.pk}/evidence/",
        {"skill_id": skill.pk, "outcome": "VERIFIED", "method": "TEST", "reason": "Me"},
        JSON,
    )
    assert response.status_code == 403


def test_unmet_decision_moves_to_unmet_group_and_later_verified_clears_it(org, reviewer, project):
    """AC-RANK-09"""
    profile = _candidate_b(org, reviewer)
    skill = SkillNode.objects.get(canonical_name="Migration validation")
    record_skill_decision(profile, skill, Outcome.UNMET, "No such experience.", reviewer, org)
    first = _run(project, reviewer)
    assert first.results.get(profile=profile).review_group == "UNMET"
    record_skill_decision(
        profile, skill, Outcome.VERIFIED, "Interviewed.", reviewer, org, "INTERVIEW"
    )
    second = _run(project, reviewer, key="k2")
    result = second.results.get(profile=profile)
    assert (result.review_group, result.coverage) == ("READY", Decimal("100.00"))


def test_override_needs_a_reason_and_changes_no_score(org, reviewer, project):
    """AC-RANK-22"""
    profile = _candidate_b(org, reviewer)
    skill = SkillNode.objects.get(canonical_name="ENOVIA configuration")
    first = _run(project, reviewer).results.get(profile=profile).coverage
    with pytest.raises(ReviewRefused):
        record_skill_decision(profile, skill, Outcome.OVERRIDE, " ", reviewer, org)
    record_skill_decision(profile, skill, Outcome.OVERRIDE, "Client asked.", reviewer, org)
    assert _run(project, reviewer, key="k2").results.get(profile=profile).coverage == first


def test_draft_rubric_refuses_a_run(org, reviewer):
    """AC-PROJ-11"""
    project = make_project(org, approved=False)
    with pytest.raises(RunRefused):
        create_run(project, "k", {}, reviewer, org)
    response = client_for(reviewer).post(
        f"/api/projects/{project.pk}/runs/", {}, JSON, HTTP_IDEMPOTENCY_KEY="k"
    )
    assert response.status_code == 400


def test_closed_project_refuses_a_run_and_a_missing_key_is_refused(org, reviewer, project):
    """AC-PROJ-02"""
    with pytest.raises(RunRefused):
        create_run(project, "", {}, reviewer, org)
    project.status = "CLOSED"
    project.save()
    with pytest.raises(RunRefused):
        create_run(project, "k", {}, reviewer, org)


def test_run_for_another_organisations_project_is_refused(org, reviewer):
    """AC-AUTH-14"""
    project = make_project(make_org())
    with pytest.raises(RunRefused):
        create_run(project, "k", {}, reviewer, org)


def test_reproduce_route_reports_identical(org, reviewer, project):
    """AC-RANK-04"""
    make_profile(org)
    run = _run(project, reviewer)
    body = client_for(reviewer).post(f"/api/runs/{run.pk}/reproduce/", {}, JSON).json()
    assert body["identical"] is True


def test_project_runs_list_and_run_detail(org, reviewer, project):
    """AC-RANK-01"""
    run = _run(project, reviewer)
    client = client_for(reviewer)
    assert client.get(f"/api/projects/{project.pk}/runs/").json()[0]["id"] == str(run.pk)
    assert client.get(f"/api/runs/{run.pk}/").json()["algorithm_version"] == "1.1"
