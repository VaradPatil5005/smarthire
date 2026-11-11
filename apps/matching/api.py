import uuid

from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api import HasMembership, IsStaffRole, get_for_org, org_of
from apps.projects.models import Project
from apps.talent.models import TalentProfile

from .models import EvidenceSpan, MatchResult, MatchRun, Outcome, SkillNode
from .services import (
    IdempotencyConflict,
    ReviewRefused,
    RunRefused,
    create_run,
    decide_span,
    later_changes,
    record_skill_decision,
    reproduce_run,
)

GROUP_FILTER = {"ready": "READY", "clarification": "NEEDS_CLARIFICATION", "unmet": "UNMET"}


def filtered_results(run, group=None, resource_type=None, q=None, with_evidence=False):
    """The one filter behind the screen, the API and both exports, so totals always agree."""
    results = run.results.select_related("profile")
    if group:
        results = results.filter(review_group=GROUP_FILTER.get(group, group))
    if resource_type:
        results = results.filter(resource_type_snapshot=resource_type)
    if q:
        results = results.filter(name_snapshot__icontains=q)
    if with_evidence:
        results = results.filter(contributions__evidence_factor__gt=0).distinct()
    return results


def contribution_body(contribution):
    span = contribution.evidence_span
    return {
        "skill": contribution.skill.canonical_name,
        "importance": contribution.importance,
        "weight": contribution.weight,
        "e": str(contribution.evidence_factor),
        "credit": str(contribution.credit),
        "label": contribution.label,
        "duration_estimated": contribution.duration_estimated,
        "evidence_span": str(span.pk) if span else None,
        "passage": span.quote if span else None,
        "page": span.page if span else None,
    }


def result_body(result):
    contributions = list(result.contributions.select_related("skill", "evidence_span"))
    buckets = {"matched": [], "unresolved": [], "missing": []}
    for contribution in contributions:
        buckets[contribution.bucket].append(contribution_body(contribution))
    return {
        "id": str(result.pk),
        "profile": str(result.profile_id),
        "name": result.name_snapshot,
        "resource_type": result.resource_type_snapshot,
        "coverage": str(result.coverage),
        "staffing_fit": str(result.staffing_fit),
        "availability_unknown": result.availability_unknown,
        "mandatory_coverage": str(result.mandatory_coverage),
        "missing_must_haves": result.missing_must_haves,
        "review_group": result.review_group,
        "group_reason": result.group_reason,
        "rank": result.rank,
        **buckets,
        "change_reasons": result.change_reasons,
        "later_changes": later_changes(result),
    }


def run_body(run):
    return {
        "id": str(run.pk),
        "project": str(run.project_id),
        "rubric_version": run.rubric_version.version,
        "dictionary_version": run.dictionary_version.number,
        "algorithm_version": run.algorithm_version,
        "run_date": run.run_date.isoformat(),
        "status": run.status,
        "results": run.results.count(),
    }


class SkillListView(APIView):
    permission_classes = [HasMembership]
    serializer_class = None

    def get(self, request):
        return Response(
            [
                {"id": s.pk, "name": s.canonical_name, "category": s.category}
                for s in SkillNode.objects.all()
            ]
        )


class ProjectRunsView(APIView):
    permission_classes = [IsStaffRole]
    serializer_class = None

    def get(self, request, pk):
        project = get_for_org(Project.objects, org_of(request), pk=pk)
        return Response([run_body(r) for r in project.runs.all()])

    def post(self, request, pk):
        project = get_for_org(Project.objects, org_of(request), pk=pk)
        key = request.headers.get("Idempotency-Key", "")
        payload = {"run_date": request.data.get("run_date")} if request.data.get("run_date") else {}
        try:
            run, created = create_run(project, key, payload, request.user, org_of(request))
        except IdempotencyConflict:
            return Response(
                {"detail": "This Idempotency-Key was used with a different payload."},
                status=status.HTTP_409_CONFLICT,
            )
        except RunRefused as refused:
            return Response({"detail": str(refused)}, status=status.HTTP_400_BAD_REQUEST)
        code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(run_body(run), status=code)


class RunDetailView(APIView):
    permission_classes = [IsStaffRole]
    serializer_class = None

    def get(self, request, pk):
        return Response(run_body(get_for_org(MatchRun.objects, org_of(request), pk=pk)))


class RunResultsView(APIView):
    permission_classes = [IsStaffRole]
    serializer_class = None
    page_size = 25

    def get(self, request, pk):
        run = get_for_org(MatchRun.objects, org_of(request), pk=pk)
        results = filtered_results(
            run,
            request.query_params.get("group"),
            request.query_params.get("resource_type"),
            request.query_params.get("q"),
            request.query_params.get("evidence") == "1",
        )
        try:
            page = max(1, int(request.query_params.get("page", 1)))
        except ValueError:
            page = 1
        start = (page - 1) * self.page_size
        items = results[start : start + self.page_size]
        return Response(
            {
                "count": results.count(),
                "page": page,
                "page_size": self.page_size,
                "results": [result_body(r) for r in items],
            }
        )


class RunReproduceView(APIView):
    permission_classes = [IsStaffRole]
    serializer_class = None

    def post(self, request, pk):
        run = get_for_org(MatchRun.objects, org_of(request), pk=pk)
        return Response(reproduce_run(run))


class ResultReviewsView(APIView):
    """Record a human decision with a reason. A candidate is refused before anything is read."""

    permission_classes = [IsStaffRole]
    serializer_class = None

    def post(self, request, pk):
        result = get_for_org(MatchResult.objects.select_related("profile"), org_of(request), pk=pk)
        return decision_response(request, result.profile)


class ProfileReviewsView(APIView):
    """The same decisions before any run exists, to accept evidence on a profile."""

    permission_classes = [IsStaffRole]
    serializer_class = None

    def get(self, request, pk):
        profile = get_for_org(TalentProfile.objects, org_of(request), pk=pk)
        return Response(
            [
                {
                    "id": str(s.pk),
                    "skill": s.skill.canonical_name,
                    "quote": s.quote,
                    "page": s.page,
                    "section": s.section,
                    "state": s.state,
                    "ambiguous": s.ambiguous,
                }
                for s in profile.spans.select_related("skill")
            ]
        )

    def post(self, request, pk):
        profile = get_for_org(TalentProfile.objects, org_of(request), pk=pk)
        return decision_response(request, profile)


def span_for(organisation, profile, span_id):
    """A malformed ID is simply an ID that does not exist."""
    try:
        span_uuid = uuid.UUID(str(span_id))
    except ValueError:
        return None
    return EvidenceSpan.objects.for_org(organisation).filter(pk=span_uuid, profile=profile).first()


def decision_response(request, profile):
    organisation = org_of(request)
    outcome = request.data.get("outcome", "")
    reason = request.data.get("reason", "")
    try:
        if outcome in (Outcome.ACCEPT, Outcome.EXCLUDE):
            span = span_for(organisation, profile, request.data.get("span_id"))
            if span is None:
                raise Http404
            decision = decide_span(
                span, outcome, reason, request.user, organisation, request.data.get("months")
            )
        else:
            skill_id = str(request.data.get("skill_id", ""))
            skill = (
                SkillNode.objects.filter(pk=int(skill_id)).first() if skill_id.isdigit() else None
            )
            if skill is None:
                return Response({"detail": "Unknown skill."}, status=status.HTTP_400_BAD_REQUEST)
            decision = record_skill_decision(
                profile,
                skill,
                outcome,
                reason,
                request.user,
                organisation,
                request.data.get("method", ""),
            )
    except ReviewRefused as refused:
        return Response({"detail": str(refused)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(
        {"id": str(decision.pk), "outcome": decision.outcome}, status=status.HTTP_201_CREATED
    )
