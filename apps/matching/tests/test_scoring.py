"""Scoring Rule v1.1: exact numbers from docs/architecture/scoring.md, plus properties."""

import inspect
import socket
from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from apps.matching import scoring
from apps.matching.scoring import (
    CORROBORATED,
    EXCLUDED,
    INFERRED,
    INTERNAL,
    NEEDS_CLARIFICATION,
    PROVISIONAL,
    READY,
    REQUIRED,
    SELF_REPORTED,
    UNKNOWN,
    UNMET,
    VERIFIED,
    Availability,
    Evidence,
    ProjectTiming,
    RubricSkill,
    rank_candidates,
    score_candidate,
)

ENOVIA, MIGRATION, PYTHON = 1, 2, 3
RUN_DATE = date(2026, 11, 8)
START = RUN_DATE + timedelta(days=30)
RUBRIC = [
    RubricSkill(ENOVIA, 5, REQUIRED),
    RubricSkill(MIGRATION, 3, REQUIRED),
    RubricSkill(PYTHON, 2, "PREFERRED"),
]
EXTERNAL = Availability("EXTERNAL", notice_days=0)
TIMING = ProjectTiming(START)


def _score(evidence, rubric=RUBRIC, parents=None, availability=EXTERNAL, timing=TIMING, **kwargs):
    return score_candidate(
        rubric, evidence, parents or {}, availability, timing, RUN_DATE, **kwargs
    )


def test_candidate_a_scores_65_and_needs_clarification():
    """AC-MATCH-15"""
    score = _score([Evidence(ENOVIA, CORROBORATED), Evidence(MIGRATION, SELF_REPORTED)])
    assert score.coverage == Decimal("65.00")
    assert score.review_group == NEEDS_CLARIFICATION


def test_candidate_b_scores_70_and_needs_clarification():
    """AC-MATCH-16"""
    score = _score([Evidence(ENOVIA, CORROBORATED), Evidence(PYTHON, CORROBORATED)])
    assert score.coverage == Decimal("70.00")
    assert score.review_group == NEEDS_CLARIFICATION


def test_candidate_b_with_accepted_line_scores_100_and_is_ready():
    """AC-MATCH-18 at function level; the pipeline version is in apps/matching/tests/test_review."""
    score = _score([Evidence(s, CORROBORATED) for s in (ENOVIA, MIGRATION, PYTHON)])
    assert score.coverage == Decimal("100.00")
    assert score.review_group == READY


@pytest.mark.parametrize(
    ("label", "factor"),
    [
        (CORROBORATED, "1.00"),
        (VERIFIED, "1.00"),
        (SELF_REPORTED, "0.50"),
        (INFERRED, "0.50"),
        (PROVISIONAL, "0.00"),
        (EXCLUDED, "0.00"),
        (UNKNOWN, "0.00"),
    ],
)
def test_each_state_gives_one_factor_and_label(label, factor):
    """AC-MATCH-14"""
    score = _score([Evidence(ENOVIA, label)], rubric=[RubricSkill(ENOVIA, 10, REQUIRED)])
    assert score.contributions[0].evidence_factor == Decimal(factor)
    assert score.contributions[0].label == label


def test_nothing_visible_is_labelled_unknown():
    """AC-MATCH-14"""
    score = _score([], rubric=[RubricSkill(ENOVIA, 10, REQUIRED)])
    assert score.contributions[0].label == UNKNOWN
    assert score.contributions[0].bucket == "missing"


@pytest.mark.parametrize(("months", "coverage"), [(3, "25.00"), (12, "100.00"), (36, "100.00")])
def test_duration_fulfilment(months, coverage):
    """AC-MATCH-19"""
    rubric = [RubricSkill(ENOVIA, 10, REQUIRED, required_months=12)]
    score = _score([Evidence(ENOVIA, CORROBORATED, months=months)], rubric=rubric)
    assert score.coverage == Decimal(coverage)


def test_unknown_months_use_6_and_are_labelled():
    """AC-MATCH-20"""
    rubric = [RubricSkill(ENOVIA, 10, REQUIRED, required_months=12)]
    score = _score([Evidence(ENOVIA, CORROBORATED)], rubric=rubric)
    assert score.coverage == Decimal("50.00")
    assert score.contributions[0].duration_estimated is True


def test_inference_is_child_to_parent_only():
    """AC-MATCH-06"""
    mql, platform, django = 10, 11, 12
    parents = {mql: platform}
    rubric = [RubricSkill(platform, 10, REQUIRED)]
    assert _score([Evidence(mql, CORROBORATED)], rubric, parents).contributions[0].label == INFERRED
    child_rubric = [RubricSkill(mql, 10, REQUIRED)]
    assert (
        _score([Evidence(platform, CORROBORATED)], child_rubric, parents).contributions[0].label
        == UNKNOWN
    )
    assert _score([Evidence(mql, CORROBORATED)], [RubricSkill(django, 10, REQUIRED)]).coverage == 0


def test_provisional_child_implies_nothing():
    """AC-MATCH-13: inference starts only from credited evidence."""
    rubric = [RubricSkill(11, 10, REQUIRED)]
    score = _score([Evidence(10, PROVISIONAL)], rubric, {10: 11})
    assert score.coverage == 0


@given(st.integers(min_value=1, max_value=200))
def test_repetition_adds_nothing(times):
    """AC-MATCH-12, atk_16's proof layer"""
    once = _score([Evidence(ENOVIA, CORROBORATED)])
    many = _score([Evidence(ENOVIA, CORROBORATED)] * times)
    assert once.coverage == many.coverage
    assert once.review_group == many.review_group


LABELS = st.sampled_from([CORROBORATED, VERIFIED, SELF_REPORTED, PROVISIONAL, EXCLUDED])
EVIDENCE = st.lists(
    st.builds(
        Evidence,
        skill_id=st.integers(1, 6),
        label=LABELS,
        months=st.one_of(st.none(), st.integers(0, 120)),
    ),
    max_size=12,
)
RUBRICS = st.lists(
    st.builds(
        RubricSkill,
        skill_id=st.integers(1, 6),
        weight=st.integers(1, 20),
        importance=st.sampled_from([REQUIRED, "PREFERRED"]),
        required_months=st.integers(0, 60),
    ),
    min_size=1,
    max_size=6,
    unique_by=lambda skill: skill.skill_id,
)


@given(RUBRICS, EVIDENCE)
def test_coverage_stays_in_bounds_and_ignores_order(rubric, evidence):
    """AC-MATCH-21"""
    score = _score(evidence, rubric)
    assert Decimal(0) <= score.coverage <= Decimal(100)
    reordered = _score(list(reversed(evidence)), list(reversed(rubric)))
    assert reordered.coverage == score.coverage
    assert reordered.review_group == score.review_group


def test_scoring_is_pure_and_takes_no_text(monkeypatch):
    """AC-MATCH-22"""

    def no_network(*args, **kwargs):
        raise AssertionError("scoring opened a socket")

    monkeypatch.setattr(socket, "socket", no_network)
    assert _score([Evidence(ENOVIA, CORROBORATED)]).coverage == Decimal("50.00")
    parameters = inspect.signature(score_candidate).parameters
    assert not {"text", "resume", "visible_text", "raw_text"} & set(parameters)
    source = inspect.getsource(scoring)
    for banned in ("django.db", "requests", "openai", "anthropic", "import socket"):
        assert banned not in source


@pytest.mark.parametrize(
    ("allocation", "required", "fit"), [(20, 100, "80.00"), (80, 50, "40.00"), (0, 50, "100.00")]
)
def test_capacity(allocation, required, fit):
    """AC-RANK-16"""
    availability = Availability(INTERNAL, allocation_pct=allocation, available_from=START)
    score = _score([], availability=availability, timing=ProjectTiming(START, required))
    assert score.staffing_fit == Decimal(fit)


@pytest.mark.parametrize(
    ("days_late", "fit"), [(0, "100.00"), (15, "75.00"), (30, "50.00"), (31, "0.00")]
)
def test_readiness_falls_linearly(days_late, fit):
    """AC-RANK-17"""
    availability = Availability(
        INTERNAL, allocation_pct=0, available_from=START + timedelta(days=days_late)
    )
    assert _score([], availability=availability).staffing_fit == Decimal(fit)


@pytest.mark.parametrize(("notice", "fit"), [(60, "50.00"), (61, "0.00")])
def test_external_notice_period(notice, fit):
    """AC-RANK-18"""
    score = _score([], availability=Availability("EXTERNAL", notice_days=notice))
    assert score.staffing_fit == Decimal(fit)
    assert score.availability_unknown is False


def test_unknown_notice_is_50_and_labelled():
    """AC-RANK-18"""
    score = _score([], availability=Availability("EXTERNAL"))
    assert score.staffing_fit == Decimal("50.00")
    assert score.availability_unknown is True


@given(
    st.integers(0, 100),
    st.integers(0, 100),
    st.one_of(st.none(), st.integers(0, 365)),
    EVIDENCE,
)
def test_availability_never_changes_coverage(first, second, notice, evidence):
    """AC-RANK-19"""
    one = _score(evidence, availability=Availability(INTERNAL, first, START))
    two = _score(evidence, availability=Availability(INTERNAL, second, START))
    three = _score(evidence, availability=Availability("EXTERNAL", notice_days=notice))
    assert one.coverage == two.coverage == three.coverage


def test_group_cases_and_precedence():
    """AC-RANK-09"""
    both = [Evidence(ENOVIA, CORROBORATED), Evidence(MIGRATION, VERIFIED)]
    assert _score(both).review_group == READY
    self_reported = [Evidence(ENOVIA, CORROBORATED), Evidence(MIGRATION, SELF_REPORTED)]
    assert _score(self_reported).review_group == NEEDS_CLARIFICATION
    assert _score([Evidence(ENOVIA, CORROBORATED)]).review_group == NEEDS_CLARIFICATION
    provisional = [Evidence(ENOVIA, CORROBORATED), Evidence(MIGRATION, PROVISIONAL)]
    assert _score(provisional).review_group == NEEDS_CLARIFICATION
    assert _score(both, file_unreadable=True).review_group == NEEDS_CLARIFICATION
    assert _score(both, unmet_skill_ids=[MIGRATION]).review_group == UNMET
    assert _score(both, file_unreadable=True, unmet_skill_ids=[ENOVIA]).review_group == UNMET


def test_must_have_only_inferred_needs_clarification():
    """AC-RANK-09 (F-17)"""
    rubric = [RubricSkill(11, 10, REQUIRED)]
    assert _score([Evidence(10, CORROBORATED)], rubric, {10: 11}).review_group == (
        NEEDS_CLARIFICATION
    )


def test_must_have_short_of_months_still_counts_as_met_for_grouping():
    """AC-RANK-09 (F-17)"""
    rubric = [RubricSkill(ENOVIA, 10, REQUIRED, required_months=12)]
    score = _score([Evidence(ENOVIA, CORROBORATED, months=3)], rubric)
    assert (score.review_group, score.coverage) == (READY, Decimal("25.00"))


def test_missing_must_have_count_and_mandatory_coverage():
    """AC-RANK-12, AC-RANK-14"""
    score = _score([Evidence(ENOVIA, CORROBORATED), Evidence(PYTHON, CORROBORATED)])
    assert score.missing_must_haves == 1
    assert score.mandatory_coverage == Decimal("62.50")


def _ranked(*scores):
    return [
        (pid, rank, position)
        for pid, _s, rank, position in rank_candidates(
            [(f"p{i}", s) for i, s in enumerate(scores, start=1)]
        )
    ]


def _plain(group=READY, coverage="50", fit="50", mandatory="50", missing=0):
    return scoring.CandidateScore(
        coverage=Decimal(coverage),
        staffing_fit=Decimal(fit),
        availability_unknown=False,
        mandatory_coverage=Decimal(mandatory),
        missing_must_haves=missing,
        review_group=group,
        group_reason="",
        contributions=(),
    )


@pytest.mark.parametrize(
    ("better", "worse"),
    [
        pytest.param({"group": READY}, {"group": UNMET, "coverage": "99"}, id="group"),
        pytest.param({"coverage": "60"}, {"coverage": "50", "fit": "99"}, id="coverage"),
        pytest.param({"fit": "60"}, {"fit": "50", "mandatory": "99"}, id="staffing-fit"),
        pytest.param({"mandatory": "60"}, {"mandatory": "50"}, id="mandatory"),
        pytest.param({"missing": 0}, {"missing": 1}, id="missing-must-haves"),
    ],
)
def test_each_sort_key_decides_in_order(better, worse):
    """AC-RANK-12"""
    ordered = rank_candidates([("a-worse", _plain(**worse)), ("z-better", _plain(**better))])
    assert ordered[0][0] == "z-better"


def test_profile_id_only_orders_display_and_ties_keep_one_rank():
    """AC-RANK-12, AC-RANK-13"""
    ranked = _ranked(_plain(), _plain(), _plain(coverage="10"))
    assert ranked == [("p1", 1, 1), ("p2", 1, 2), ("p3", 3, 3)]


def test_rank_restarts_in_each_group():
    """AC-RANK-13"""
    ranked = _ranked(_plain(), _plain(group=NEEDS_CLARIFICATION))
    assert [r[1] for r in ranked] == [1, 1]
