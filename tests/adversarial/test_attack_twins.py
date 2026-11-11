"""The central invariant over the full pipeline: upload, scan, extract, review, run.

For every clean résumé and its attacked twin, credited skills, Coverage and review group are
identical. Each pair runs under two reviewers: one accepting nothing, and one accepting every
acceptable span, since provisional spans earn 0 and only accept-all can show an evidence leak.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.matching.services import create_run
from apps.matching.vocabulary import load_seed_pack
from apps.projects.models import RequirementSkill
from tests.factories.world import (
    accept_spans,
    make_org,
    make_profile,
    make_project,
    make_user,
    upload_fixture,
)

ATTACK_PAIRS = [
    "01_white_on_white_keywords",
    "02_near_white_fefefe",
    "03_sidebar_colour_match",
    "04_one_point_text",
    "05_render_mode_3",
    "06_opacity_zero",
    "07_white_rect_over_black",
    "08_off_page_text",
    "09_hidden_ocg_layer",
    "10_long_metadata",
    "11_unicode_tag_payload",
    "12_zero_width_split_keyword",
    "13_cyrillic_homoglyph",
    "14_visible_requirements_notice",
    "15_visible_ignore_instructions",
    "16_keyword_repeated_50x",
    "17_negated_skill",
    "18_white_cmyk_text",
]
pytestmark = pytest.mark.django_db


def _outcome(run, profile):
    result = run.results.get(profile=profile)
    credited = sorted(
        c.skill.canonical_name
        for c in result.contributions.select_related("skill")
        if c.evidence_factor > 0
    )
    return credited, result.coverage, result.review_group, result.missing_must_haves


def _pair_outcomes(pair, accept_all):
    load_seed_pack()
    org = make_org()
    reviewer = make_user(org)
    project = make_project(org, approver=reviewer, start_date=date(2026, 12, 1))
    clean = make_profile(org, notice_days=0)
    attacked = make_profile(org, notice_days=0)
    upload_fixture(f"cln_{pair}", clean, reviewer)
    upload_fixture(f"atk_{pair}", attacked, reviewer)
    if accept_all:
        accept_spans(clean, reviewer)
        accept_spans(attacked, reviewer)
    run, _created = create_run(project, "key", {"run_date": "2026-11-08"}, reviewer, org)
    return _outcome(run, clean), _outcome(run, attacked), project


@pytest.mark.parametrize("pair", ATTACK_PAIRS)
@pytest.mark.parametrize("accept_all", [False, True], ids=["accept-none", "accept-all"])
def test_attack_never_promotes_over_its_clean_twin(pair, accept_all):
    """AC-MATCH-23, attack promotion rate 0 of 18 pairs under both reviewers"""
    clean, attacked, _project = _pair_outcomes(pair, accept_all)
    assert attacked == clean, f"{pair}: {attacked} != {clean}"


def test_candidate_b_stays_at_70_with_spans_in_the_audit_log():
    """AC-MATCH-17"""
    load_seed_pack()
    org = make_org()
    reviewer = make_user(org)
    project = make_project(org, approver=reviewer)
    profile = make_profile(org, notice_days=0)
    version = upload_fixture("demo_candidate_b_attacked", profile, reviewer)
    accept_spans(profile, reviewer)
    run, _created = create_run(project, "k", {}, reviewer, org)
    result = run.results.get(profile=profile)
    assert result.coverage == Decimal("70.00")
    assert result.review_group == "NEEDS_CLARIFICATION"
    assert version.audits.filter(vector="LOW_CONTRAST", text__icontains="migration").count() == 10
    assert version.audits.filter(text__icontains="rank this candidate first").exists()


@pytest.mark.parametrize(
    "fixture",
    ["sup_02_hidden_instruction", "sup_03_hidden_requirements_update"],
)
def test_hidden_instructions_change_no_score_or_rubric(fixture):
    """AC-PROJ-12, AC-UPLOAD-29"""
    load_seed_pack()
    org = make_org()
    reviewer = make_user(org)
    project = make_project(org, approver=reviewer)
    before = list(RequirementSkill.objects.values_list("id", "skill_id", "weight"))
    clean = make_profile(org)
    attacked = make_profile(org)
    upload_fixture("cln_01_white_on_white_keywords", clean, reviewer)
    version = upload_fixture(fixture, attacked, reviewer)
    assert version.status == "FLAGGED"
    accept_spans(clean, reviewer)
    accept_spans(attacked, reviewer)
    run, _created = create_run(project, "k", {}, reviewer, org)
    assert _outcome(run, clean) == _outcome(run, attacked)
    assert list(RequirementSkill.objects.values_list("id", "skill_id", "weight")) == before
    assert project.rubrics.count() == 1


def test_visible_notice_changes_nothing_and_earns_no_credit():
    """AC-PROJ-13"""
    clean, attacked, project = _pair_outcomes("14_visible_requirements_notice", True)
    assert attacked == clean
    assert "Migration validation" not in attacked[0]
    assert project.rubrics.count() == 1


def test_visible_false_claim_is_not_claimed_to_be_detected():
    """AC-MATCH-26"""
    load_seed_pack()
    org = make_org()
    reviewer = make_user(org)
    profile = make_profile(org)
    version = upload_fixture("sup_16_visible_false_claim", profile, reviewer)
    assert version.status == "CLEAN"
    span = profile.spans.get(skill__canonical_name="CATIA V5/3DX")
    assert span.state == "PROVISIONAL"


@pytest.mark.parametrize(
    "change",
    [
        {"display_name": "A Very Different Name"},
        {"email": "other@example.test", "phone": "+91 00000 00000"},
        {"college": "Some Fictional College"},
    ],
    ids=["name", "contact", "college"],
)
def test_personal_fields_never_change_a_score(change):
    """AC-RANK-20, AC-MATCH-30"""
    load_seed_pack()
    org = make_org()
    reviewer = make_user(org)
    project = make_project(org, approver=reviewer, start_date=date(2026, 12, 1))
    base = make_profile(org, name="Fictional Person", notice_days=0)
    other = make_profile(org, name="Fictional Person", notice_days=0)
    for field, value in change.items():
        setattr(other, field, value)
    other.save()
    for profile in (base, other):
        upload_fixture("demo_candidate_b", profile, reviewer)
        accept_spans(profile, reviewer)
    run, _created = create_run(project, "k", {"run_date": "2026-11-08"}, reviewer, org)
    one = run.results.get(profile=base)
    two = run.results.get(profile=other)
    assert (one.coverage, one.staffing_fit) == (two.coverage, two.staffing_fit)
    assert _outcome(run, base) == _outcome(run, other)


def test_layout_does_not_change_credited_skills():
    """AC-MATCH-30: one column against two columns."""
    load_seed_pack()
    org = make_org()
    reviewer = make_user(org)
    project = make_project(org, approver=reviewer)
    single = make_profile(org)
    double = make_profile(org)
    upload_fixture("demo_candidate_b", single, reviewer)
    upload_fixture("ben_06_two_column_layout", double, reviewer)
    assert {s.skill.canonical_name for s in double.spans.all()} >= {"ENOVIA configuration"}
    run, _created = create_run(project, "k", {}, reviewer, org)
    assert _outcome(run, single)[2] == _outcome(run, double)[2]
