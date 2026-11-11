"""Scoring Rule v1.1 (docs/architecture/scoring.md). A pure function of structured records.

Nothing here reads résumé text, the database, the clock or the network. Rerunning it on stored
inputs gives identical results, which is what makes old runs reproducible.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

ESTIMATED_MONTHS = 6
UNKNOWN_AVAILABILITY_FIT = Decimal("50.00")
LATE_LIMIT_DAYS = 30

REQUIRED = "REQUIRED"
INTERNAL = "INTERNAL"

READY = "READY"
NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
UNMET = "UNMET"
GROUP_ORDER = {READY: 0, NEEDS_CLARIFICATION: 1, UNMET: 2}

CORROBORATED = "Corroborated"
VERIFIED = "Verified"
SELF_REPORTED = "Self-reported"
INFERRED = "Inferred"
PROVISIONAL = "Provisional"
UNKNOWN = "Unknown"
EXCLUDED = "Excluded"

EVIDENCE_FACTOR = {
    CORROBORATED: Fraction(1),
    VERIFIED: Fraction(1),
    SELF_REPORTED: Fraction(1, 2),
    INFERRED: Fraction(1, 2),
    PROVISIONAL: Fraction(0),
    UNKNOWN: Fraction(0),
    EXCLUDED: Fraction(0),
}
BUCKET = {
    CORROBORATED: "matched",
    VERIFIED: "matched",
    SELF_REPORTED: "unresolved",
    INFERRED: "unresolved",
    PROVISIONAL: "unresolved",
    UNKNOWN: "missing",
    EXCLUDED: "missing",
}
# A label that outranks another at equal e. Provisional outranks Excluded: it may still be accepted.
_LABEL_RANK = {
    VERIFIED: 6,
    CORROBORATED: 5,
    SELF_REPORTED: 4,
    INFERRED: 3,
    PROVISIONAL: 2,
    EXCLUDED: 1,
    UNKNOWN: 0,
}
_MATCHED = (CORROBORATED, VERIFIED)
_MISSING = (UNKNOWN, EXCLUDED)


@dataclass(frozen=True)
class RubricSkill:
    skill_id: int
    weight: int
    importance: str
    required_months: int = 0


@dataclass(frozen=True)
class Evidence:
    skill_id: int
    label: str
    months: int | None = None
    span_id: str | None = None


@dataclass(frozen=True)
class Availability:
    resource_type: str
    allocation_pct: int | None = None
    available_from: date | None = None
    notice_days: int | None = None


@dataclass(frozen=True)
class ProjectTiming:
    start_date: date | None
    required_allocation_pct: int = 100


@dataclass(frozen=True)
class Contribution:
    skill_id: int
    importance: str
    weight: int
    evidence_factor: Decimal
    credit: Decimal
    label: str
    bucket: str
    duration_estimated: bool
    span_id: str | None


@dataclass(frozen=True)
class CandidateScore:
    coverage: Decimal
    staffing_fit: Decimal
    availability_unknown: bool
    mandatory_coverage: Decimal
    missing_must_haves: int
    review_group: str
    group_reason: str
    contributions: tuple[Contribution, ...]


def _two_places(value) -> Decimal:
    exact = Decimal(value.numerator) / Decimal(value.denominator)
    return exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _ancestors(skill_id, parents):
    seen = set()
    current = parents.get(skill_id)
    while current is not None and current not in seen:
        seen.add(current)
        yield current
        current = parents.get(current)


def _with_inference(evidence, parents):
    """Credited evidence implies its ancestors at Inferred. It runs child to parent only."""
    expanded = list(evidence)
    for item in evidence:
        if EVIDENCE_FACTOR[item.label] > 0:
            for ancestor in _ancestors(item.skill_id, parents):
                expanded.append(Evidence(ancestor, INFERRED, item.months, item.span_id))
    return expanded


def _best_evidence(evidence):
    """A skill is credited once, at its highest level. Repetition adds nothing."""
    best = {}
    for item in evidence:
        current = best.get(item.skill_id)
        months = -1 if item.months is None else item.months
        key = (_LABEL_RANK[item.label], months, item.span_id or "")
        if current is None or key > current[0]:
            best[item.skill_id] = (key, item)
    return {skill_id: entry[1] for skill_id, entry in best.items()}


def _credit(item, required_months):
    factor = EVIDENCE_FACTOR[item.label]
    if factor == 0:
        return Fraction(0), False
    estimated = item.months is None
    months = ESTIMATED_MONTHS if estimated else item.months
    return factor * min(Fraction(1), Fraction(months, max(1, required_months))), estimated


def _weighted_percentage(pairs):
    total = sum(weight for weight, _credit_value in pairs)
    if not total:
        return Fraction(0)
    return 100 * sum(weight * credit for weight, credit in pairs) / total


def staffing_fit(availability, project, run_date):
    """Return (fit, unknown). Timing and capacity only, so Coverage can never depend on this."""
    start = None
    capacity = Fraction(1)
    if availability.resource_type == INTERNAL:
        if availability.allocation_pct is None:
            return UNKNOWN_AVAILABILITY_FIT, True
        free = 100 - availability.allocation_pct
        capacity = min(Fraction(1), Fraction(free, max(1, project.required_allocation_pct)))
        start = availability.available_from
    elif availability.notice_days is not None:
        start = date.fromordinal(run_date.toordinal() + availability.notice_days)
    if start is None or project.start_date is None:
        return UNKNOWN_AVAILABILITY_FIT, True
    days_late = (start - project.start_date).days
    if days_late <= 0:
        readiness = Fraction(1)
    elif days_late <= LATE_LIMIT_DAYS:
        readiness = 1 - Fraction(days_late, 2 * LATE_LIMIT_DAYS)
    else:
        readiness = Fraction(0)
    return _two_places(100 * capacity * readiness), False


def _review_group(required_labels, unmet_skill_ids, file_unreadable, rubric):
    required_ids = {s.skill_id for s in rubric if s.importance == REQUIRED}
    if required_ids & set(unmet_skill_ids):
        return UNMET, "A reviewer confirmed a must-have is not met."
    if file_unreadable:
        return NEEDS_CLARIFICATION, "The résumé could not be read. The manual form is available."
    if any(label not in _MATCHED for label in required_labels):
        return NEEDS_CLARIFICATION, "A must-have has no accepted work or project evidence yet."
    return READY, ""


def score_candidate(
    rubric,
    evidence,
    parents,
    availability,
    project,
    run_date,
    *,
    file_unreadable=False,
    unmet_skill_ids=(),
) -> CandidateScore:
    best = _best_evidence(_with_inference(evidence, parents))
    contributions = []
    all_pairs = []
    required_pairs = []
    required_labels = []
    for skill in sorted(rubric, key=lambda s: s.skill_id):
        item = best.get(skill.skill_id, Evidence(skill.skill_id, UNKNOWN))
        credit, estimated = _credit(item, skill.required_months)
        all_pairs.append((skill.weight, credit))
        if skill.importance == REQUIRED:
            required_pairs.append((skill.weight, credit))
            required_labels.append(item.label)
        contributions.append(
            Contribution(
                skill_id=skill.skill_id,
                importance=skill.importance,
                weight=skill.weight,
                evidence_factor=_two_places(EVIDENCE_FACTOR[item.label]),
                credit=Decimal(credit.numerator) / Decimal(credit.denominator),
                label=item.label,
                bucket=BUCKET[item.label],
                duration_estimated=estimated,
                span_id=item.span_id,
            )
        )
    fit, unknown = staffing_fit(availability, project, run_date)
    group, reason = _review_group(required_labels, unmet_skill_ids, file_unreadable, rubric)
    return CandidateScore(
        coverage=_two_places(_weighted_percentage(all_pairs)),
        staffing_fit=fit,
        availability_unknown=unknown,
        mandatory_coverage=_two_places(_weighted_percentage(required_pairs)),
        missing_must_haves=sum(label in _MISSING for label in required_labels),
        review_group=group,
        group_reason=reason,
        contributions=tuple(contributions),
    )


def sort_key(score: CandidateScore, profile_id: str):
    """The default order. Everything before profile ID decides merit; the ID only breaks display."""
    return (*_merit_key(score), profile_id)


def _merit_key(score):
    return (
        GROUP_ORDER[score.review_group],
        -score.coverage,
        -score.staffing_fit,
        -score.mandatory_coverage,
        score.missing_must_haves,
    )


def rank_candidates(scored):
    """Take (profile_id, score) pairs; return (profile_id, score, rank, position) in display order.

    Rank restarts in each group and skips after an exact tie (1, 1, 3).
    """
    ordered = sorted(scored, key=lambda pair: sort_key(pair[1], pair[0]))
    ranked = []
    group = None
    in_group = 0
    rank = 0
    previous = None
    for position, (profile_id, score) in enumerate(ordered, start=1):
        if score.review_group != group:
            group = score.review_group
            in_group = 0
            previous = None
        in_group += 1
        key = _merit_key(score)
        if key != previous:
            rank = in_group
            previous = key
        ranked.append((profile_id, score, rank, position))
    return ranked
