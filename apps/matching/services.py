"""Review decisions and match runs. Screen, API and export all go through these."""

import hashlib
import json
import logging
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.ingestion.models import ResumeStatus
from apps.projects.models import RubricStatus
from apps.talent.models import ClaimProvenance, TalentProfile
from apps.talent.services import ProfileInvalid, valid_months

from . import scoring
from .models import (
    ALGORITHM_VERSION,
    UNACCEPTABLE_STATES,
    EvidenceSpan,
    MatchResult,
    MatchRun,
    Method,
    Outcome,
    ReviewDecision,
    Section,
    SkillContribution,
    SkillNode,
    SpanState,
)
from .vocabulary import latest_dictionary

logger = logging.getLogger(__name__)

_FOUR_PLACES = Decimal("0.0001")


class ReviewRefused(Exception):
    """A decision that the rules do not allow, whatever the request said."""


class RunRefused(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


def _refuse_own_profile(profile, actor):
    if actor is not None and profile.owner_id == actor.pk:
        raise ReviewRefused("You cannot review your own profile.")


def _require_reason(reason):
    if not isinstance(reason, str) or not reason.strip():
        raise ReviewRefused("A reason is required.")
    return reason.strip()


@transaction.atomic
def decide_span(span, outcome, reason, actor, organisation, months=None) -> ReviewDecision:
    """Accept or exclude a proposed span. Acceptance needs the span in the visible text."""
    reason = _require_reason(reason)
    if span.organisation_id != organisation.pk:
        raise ReviewRefused("Unknown span.")
    _refuse_own_profile(span.profile, actor)
    if outcome not in (Outcome.ACCEPT, Outcome.EXCLUDE):
        raise ReviewRefused("A span can only be accepted or excluded.")
    if outcome == Outcome.ACCEPT:
        if span.state in UNACCEPTABLE_STATES:
            raise ReviewRefused(
                "Negated, aspirational or instruction-like text cannot be evidence."
            )
        text = span.resume_version.visible_text_or_none()
        if text is None or text[span.start : span.end] != span.quote:
            raise ReviewRefused("This passage is not in the visible text.")
        span.state = SpanState.ACCEPTED
        try:
            supported_months = valid_months(months)
        except ProfileInvalid as invalid:
            raise ReviewRefused(invalid.errors["months"]) from invalid
        if supported_months is not None:
            span.months = supported_months
    elif span.state not in UNACCEPTABLE_STATES:
        # A negated or aspirational span keeps its state, or a later accept would see "excluded".
        span.state = SpanState.EXCLUDED
    span.save(update_fields=["state", "months"])
    return ReviewDecision.objects.create(
        organisation=organisation,
        actor=actor,
        outcome=outcome,
        reason=reason,
        profile=span.profile,
        skill=span.skill,
        span=span,
    )


def record_skill_decision(profile, skill, outcome, reason, actor, organisation, method=""):
    """Verified (with a method) or unmet must-have. Neither needs a span."""
    reason = _require_reason(reason)
    if profile.organisation_id != organisation.pk:
        raise ReviewRefused("Unknown profile.")
    _refuse_own_profile(profile, actor)
    if outcome == Outcome.VERIFIED and method not in (Method.TEST, Method.INTERVIEW):
        raise ReviewRefused("Verified needs a method: test or interview.")
    if outcome not in (Outcome.VERIFIED, Outcome.UNMET, Outcome.OVERRIDE):
        raise ReviewRefused("Unknown outcome.")
    return ReviewDecision.objects.create(
        organisation=organisation,
        actor=actor,
        outcome=outcome,
        reason=reason,
        profile=profile,
        skill=skill,
        method=method,
    )


def _span_label(span):
    if span.state == SpanState.ACCEPTED:
        if span.section in (Section.EXPERIENCE, Section.PROJECT):
            return scoring.CORROBORATED
        return scoring.SELF_REPORTED
    if span.state == SpanState.PROVISIONAL:
        return scoring.PROVISIONAL
    return scoring.EXCLUDED


def _evidence_records(profile):
    records = []
    for span in EvidenceSpan.objects.filter(profile=profile):
        records.append(
            {
                "skill_id": span.skill_id,
                "label": _span_label(span),
                "months": span.months,
                "span_id": str(span.pk),
            }
        )
    for claim in profile.claims.all():
        if claim.provenance == ClaimProvenance.IMPORT and not claim.confirmed:
            label = scoring.PROVISIONAL
        else:
            label = scoring.SELF_REPORTED
        records.append(
            {"skill_id": claim.skill_id, "label": label, "months": claim.months, "span_id": None}
        )
    return records


def _decision_state(profile):
    """Latest word per skill. Verified adds evidence; unmet stands until a later acceptance."""
    verified = []
    unmet = {}
    for decision in ReviewDecision.objects.filter(profile=profile).order_by("created_at", "pk"):
        if decision.outcome == Outcome.VERIFIED:
            verified.append(
                {
                    "skill_id": decision.skill_id,
                    "label": scoring.VERIFIED,
                    "months": None,
                    "span_id": None,
                }
            )
            unmet.pop(decision.skill_id, None)
        elif decision.outcome == Outcome.UNMET:
            unmet[decision.skill_id] = True
        elif decision.outcome == Outcome.ACCEPT:
            unmet.pop(decision.skill_id, None)
    return verified, sorted(unmet)


def _file_unreadable(profile):
    """The newest file failed or is a full scan, and no earlier version gave readable text."""
    versions = list(profile.resumes.order_by("-version"))
    if not versions:
        return False
    usable = [
        v
        for v in versions
        if v.status in (ResumeStatus.CLEAN, ResumeStatus.FLAGGED) and not v.is_fully_scanned
    ]
    if usable:
        return False
    return versions[0].status != ResumeStatus.QUARANTINED


def _profile_inputs(profile):
    verified, unmet = _decision_state(profile)
    return {
        "evidence": _evidence_records(profile) + verified,
        "unmet": unmet,
        "file_unreadable": _file_unreadable(profile),
        "availability": {
            "resource_type": profile.resource_type,
            "allocation_pct": profile.allocation_pct,
            "available_from": profile.available_from.isoformat()
            if profile.available_from
            else None,
            "notice_days": profile.notice_days,
        },
    }


def _run_inputs(project, rubric):
    return {
        "rubric": [
            {
                "skill_id": item.skill_id,
                "weight": item.weight,
                "importance": item.importance,
                "required_months": item.required_months,
            }
            for item in rubric.skills.all()
        ],
        "parents": {str(s.pk): s.parent_id for s in SkillNode.objects.all()},
        "project": {
            "start_date": project.start_date.isoformat() if project.start_date else None,
            "required_allocation_pct": project.required_allocation_pct,
        },
    }


def score_from_inputs(run_inputs, profile_inputs, run_date):
    """The one call into the scoring function, for first runs and reproductions alike."""
    project = run_inputs["project"]
    start = project["start_date"]
    availability = profile_inputs["availability"]
    available_from = availability["available_from"]
    return scoring.score_candidate(
        [scoring.RubricSkill(**item) for item in run_inputs["rubric"]],
        [scoring.Evidence(**item) for item in profile_inputs["evidence"]],
        {int(k): v for k, v in run_inputs["parents"].items()},
        scoring.Availability(
            resource_type=availability["resource_type"],
            allocation_pct=availability["allocation_pct"],
            available_from=date.fromisoformat(available_from) if available_from else None,
            notice_days=availability["notice_days"],
        ),
        scoring.ProjectTiming(
            start_date=date.fromisoformat(start) if start else None,
            required_allocation_pct=project["required_allocation_pct"],
        ),
        run_date,
        file_unreadable=profile_inputs["file_unreadable"],
        unmet_skill_ids=profile_inputs["unmet"],
    )


def payload_hash(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def latest_completed_run(project):
    return (
        MatchRun.objects.filter(project=project, status="COMPLETED")
        .order_by("-created_at", "-pk")
        .first()
    )


def _change_reasons(previous_result, contributions, profile):
    """Explain changed evidence levels and duration credit without altering stored scores."""
    if previous_result is None:
        return []
    old = {c.skill_id: c for c in previous_result.contributions.all()}
    reasons = []
    for contribution in contributions:
        previous = old.get(contribution.skill_id)
        new_credit = contribution.credit.quantize(_FOUR_PLACES)
        if previous is None or (
            previous.evidence_factor == contribution.evidence_factor
            and previous.credit == new_credit
        ):
            continue
        decision = (
            ReviewDecision.objects.filter(profile=profile, skill_id=contribution.skill_id)
            .order_by("-created_at", "-pk")
            .first()
        )
        reasons.append(
            {
                "decision_id": str(decision.pk) if decision else None,
                "skill": SkillNode.objects.get(pk=contribution.skill_id).canonical_name,
                "old_e": str(previous.evidence_factor),
                "new_e": str(contribution.evidence_factor),
                "old_credit": str(previous.credit),
                "new_credit": str(new_credit),
                "reason": decision.reason if decision else "Evidence changed.",
            }
        )
    return reasons


def _publish(run, run_inputs, profiles_inputs, previous_run):
    scored = [
        (str(profile_id), score_from_inputs(run_inputs, inputs, run.run_date))
        for profile_id, inputs in profiles_inputs.items()
    ]
    previous = {}
    if previous_run:
        previous = {r.profile_id: r for r in previous_run.results.all()}
    for profile_id, score, rank, position in scoring.rank_candidates(scored):
        profile = TalentProfile.objects.get(pk=profile_id, organisation=run.organisation)
        result = MatchResult.objects.create(
            organisation=run.organisation,
            run=run,
            profile=profile,
            name_snapshot=profile.display_name,
            resource_type_snapshot=profile.resource_type,
            coverage=score.coverage,
            staffing_fit=score.staffing_fit,
            mandatory_coverage=score.mandatory_coverage,
            missing_must_haves=score.missing_must_haves,
            review_group=score.review_group,
            rank=rank,
            position=position,
            availability_unknown=score.availability_unknown,
            group_reason=score.group_reason,
            inputs=profiles_inputs[profile.pk],
            change_reasons=_change_reasons(previous.get(profile.pk), score.contributions, profile),
        )
        SkillContribution.objects.bulk_create(
            [
                SkillContribution(
                    result=result,
                    skill_id=c.skill_id,
                    importance=c.importance,
                    weight=c.weight,
                    evidence_factor=c.evidence_factor,
                    credit=c.credit.quantize(_FOUR_PLACES),
                    label=c.label,
                    bucket=c.bucket,
                    duration_estimated=c.duration_estimated,
                    evidence_span_id=c.span_id,
                )
                for c in score.contributions
            ]
        )


def _run_date(payload):
    if not payload.get("run_date"):
        return date.today()
    try:
        return date.fromisoformat(payload["run_date"])
    except (TypeError, ValueError) as error:
        raise RunRefused("run_date must be a date, YYYY-MM-DD.") from error


def create_run(project, key, payload, actor, organisation) -> tuple[MatchRun, bool]:
    """Run once per organisation and key. Returns (run, created).

    Results publish in one transaction, so a failure leaves the last completed shortlist in place.
    Two simultaneous requests with one key collide on the unique constraint; the loser gets the
    winner's run.
    """
    if project.organisation_id != organisation.pk:
        raise RunRefused("Unknown project.")
    if not key:
        raise RunRefused("An Idempotency-Key header is required.")
    digest = payload_hash(payload)
    existing = _existing_run(organisation, project, key, digest)
    if existing:
        return existing, False
    if project.is_closed:
        raise RunRefused("This project is closed.")
    rubric = project.latest_approved_rubric()
    if rubric is None or rubric.status != RubricStatus.APPROVED:
        raise RunRefused("A run needs an approved rubric.")
    dictionary = latest_dictionary()
    run_date = _run_date(payload)
    previous = latest_completed_run(project)
    try:
        with transaction.atomic():
            run_inputs = _run_inputs(project, rubric)
            run = MatchRun.objects.create(
                organisation=organisation,
                project=project,
                rubric_version=rubric,
                dictionary_version=dictionary,
                algorithm_version=ALGORITHM_VERSION,
                run_date=run_date,
                idempotency_key=key,
                payload_hash=digest,
                inputs=run_inputs,
                created_by=actor,
            )
            profiles = TalentProfile.objects.for_org(organisation).filter(archived_at__isnull=True)
            _publish(run, run_inputs, {p.pk: _profile_inputs(p) for p in profiles}, previous)
    except IntegrityError:
        existing = _existing_run(organisation, project, key, digest)
        if existing:
            return existing, False
        raise
    logger.info("match run completed run=%s project=%s", run.pk, project.pk)
    return run, True


def _existing_run(organisation, project, key, digest):
    run = MatchRun.objects.for_org(organisation).filter(idempotency_key=key).first()
    if run and (run.project_id != project.pk or run.payload_hash != digest):
        raise IdempotencyConflict
    return run


def reproduce_run(run):
    """Recompute a stored run from its stored inputs and compare with what was published."""
    stored = list(run.results.order_by("position"))
    scored = [
        (
            str(r.profile_id),
            score_from_inputs(run.inputs, r.inputs, run.run_date),
        )
        for r in stored
    ]
    fresh = [
        {
            "profile": profile_id,
            "coverage": str(score.coverage),
            "staffing_fit": str(score.staffing_fit),
            "group": score.review_group,
            "rank": rank,
        }
        for profile_id, score, rank, _position in scoring.rank_candidates(scored)
    ]
    published = [
        {
            "profile": str(r.profile_id),
            "coverage": str(r.coverage),
            "staffing_fit": str(r.staffing_fit),
            "group": r.review_group,
            "rank": r.rank,
        }
        for r in stored
    ]
    return {"identical": fresh == published, "results": fresh, "checked_at": timezone.now()}


def later_changes(result):
    """For an old result: what the next run said changed, and why."""
    newer = (
        MatchResult.objects.filter(
            profile=result.profile,
            run__project=result.run.project,
            run__created_at__gt=result.run.created_at,
        )
        .order_by("run__created_at")
        .first()
    )
    if newer is None:
        return None
    return {
        "run": str(newer.run_id),
        "coverage": str(newer.coverage),
        "reasons": newer.change_reasons,
    }


def assert_same_organisation(first, second):
    if first.organisation_id != second.organisation_id:
        raise ValidationError("Objects must share one organisation")
