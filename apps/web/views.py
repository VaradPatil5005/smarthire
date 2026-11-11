"""The screens. They hold no business rules: they call the same services as the API."""

import uuid
from datetime import date
from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.ingestion.models import HiddenSpanAudit, ResumeVersion
from apps.ingestion.services import UploadRefused, candidate_status, receive_upload
from apps.matching.api import filtered_results, span_for
from apps.matching.models import (
    EvidenceSpan,
    MatchResult,
    MatchRun,
    Method,
    Outcome,
    ReviewDecision,
    SkillNode,
    SpanState,
)
from apps.matching.services import (
    IdempotencyConflict,
    ReviewRefused,
    RunRefused,
    create_run,
    decide_span,
    later_changes,
    latest_completed_run,
    record_skill_decision,
)
from apps.onboarding.models import BatchStatus, ImportBatch, ImportRow, RowState
from apps.onboarding.services import (
    MAPPABLE_FIELDS,
    ImportInvalid,
    confirm_import,
    mapping_is_complete,
    preview_import,
    remap_import,
    resolve_queue_row,
    rollback_import,
    source_headers,
)
from apps.projects.models import (
    Importance,
    Project,
    ProjectStatus,
    RequirementSkill,
    RubricLocked,
)
from apps.projects.services import (
    RubricInvalid,
    add_skill,
    approve_rubric,
    next_version,
    update_skill,
)
from apps.reports.services import dashboard_totals, utilisation_summary
from apps.talent.models import DataRequest, ResourceType, TalentProfile
from apps.talent.services import ProfileInvalid, add_form_claim, validate_profile
from apps.tenancy.models import IMPORT_ROLES, RUBRIC_APPROVER_ROLES, STAFF_ROLES, Role

ROLE_HOMES = {
    Role.CANDIDATE: "me",
    Role.RECRUITER: "project-list",
    Role.DELIVERY_MANAGER: "bench",
    Role.ADMIN: "dashboard",
}
SCORE_NOTE = "Coverage of this project's criteria, not a probability of success."
GROUPS = [
    ("READY", "Ready for review"),
    ("NEEDS_CLARIFICATION", "Needs clarification"),
    ("UNMET", "Unmet must-have"),
]
PAGE_SIZE = 25
LOCKED_MESSAGE = "This version is approved and locked. Start the next version to change it."
FIELD_LABELS = {
    "external_id": "ID in the source system",
    "display_name": "Name",
    "title": "Title",
    "primary_skills": "Primary skills",
    "allocation_pct": "Allocation %",
    "available_from": "Available from",
    "notice_days": "Notice period (days)",
    "email": "Email",
    "phone": "Phone",
}
PROFILE_FIELDS = (
    "display_name",
    "title",
    "email",
    "phone",
    "college",
    "notice_days",
    "allocation_pct",
    "available_from",
)


def _member(roles=None):
    """Signed in, with an active membership, and a role allowed here. Otherwise refused."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if request.membership is None:
                raise PermissionDenied
            if roles is not None and request.membership.role not in roles:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


staff_only = _member(STAFF_ROLES)
any_member = _member()


def _org(request):
    return request.membership.organisation


def _get(model, request, **lookup):
    obj = model.objects.for_org(_org(request)).filter(**lookup).first()
    if obj is None:
        raise Http404
    return obj


def _optional_int(value):
    return int(value) if value not in (None, "") else None


def _paginate(request, items):
    """One page, plus the current query without its page number, for the page links."""
    page = Paginator(items, PAGE_SIZE).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return page, query.urlencode()


def _date_or_blank(value):
    try:
        return date.fromisoformat(value).isoformat() if value else ""
    except ValueError:
        return ""


def _clean_profile_post(post):
    data = {field: post.get(field, "").strip() for field in PROFILE_FIELDS}
    for field in ("allocation_pct", "notice_days"):
        try:
            data[field] = _optional_int(data[field])
        except ValueError as error:
            raise ProfileInvalid({field: "Enter a whole number."}) from error
    data["available_from"] = data["available_from"] or None
    return data


@require_GET
def home(request):
    if not request.user.is_authenticated:
        return redirect("login")
    if request.membership is None:
        raise PermissionDenied
    return redirect(ROLE_HOMES[request.membership.role])


def _own_profile(request):
    return (
        TalentProfile.objects.for_org(_org(request))
        .filter(owner=request.user, archived_at__isnull=True)
        .first()
    )


@any_member
def me(request):
    profile = _own_profile(request)
    errors = {}
    if request.method == "POST":
        try:
            data = _clean_profile_post(request.POST)
            for field in ("allocation_pct", "available_from"):
                data.pop(field, None)
            validate_profile(data, ResourceType.EXTERNAL)
            if profile is None:
                profile = TalentProfile.objects.create(
                    organisation=_org(request),
                    owner=request.user,
                    resource_type=ResourceType.EXTERNAL,
                    **data,
                )
            else:
                for field, value in data.items():
                    setattr(profile, field, value)
                profile.save()
            messages.success(request, "Profile saved.")
            return redirect("me")
        except ProfileInvalid as invalid:
            errors = invalid.errors
    uploads = []
    if profile:
        uploads = [
            {
                "version": v.version,
                "status": candidate_status(v),
                "recovery_message": v.recovery_message,
            }
            for v in profile.resumes.order_by("-version")
        ]
    context = {
        "profile": profile,
        "form": request.POST if request.method == "POST" else None,
        "errors": errors,
        "uploads": uploads,
        "skills": SkillNode.objects.all(),
        "claims": profile.claims.select_related("skill") if profile else [],
    }
    return render(request, "web/me.html", context)


@any_member
@require_POST
def me_add_skill(request):
    profile = _own_profile(request)
    if profile is None:
        raise Http404
    try:
        add_form_claim(
            profile, request.POST.get("skill", ""), _optional_int(request.POST.get("months"))
        )
        messages.success(request, "Skill added.")
    except (ProfileInvalid, ValueError):
        messages.error(request, "Pick a skill from the list, and enter months from 0 to 1200.")
    return redirect("me")


def _upload_and_report(request, profile):
    try:
        receive_upload(request.FILES.get("file"), profile, _org(request), request.user)
        messages.success(
            request, "File received. It stays in quarantine until it has been checked."
        )
    except UploadRefused as refused:
        messages.error(request, str(refused))


@any_member
@require_POST
def me_upload(request):
    profile = _own_profile(request)
    if profile is None:
        raise Http404
    _upload_and_report(request, profile)
    return redirect("me")


@any_member
@require_POST
def me_data_request(request):
    profile = _own_profile(request)
    kind = request.POST.get("kind")
    if profile is None or kind not in DataRequest.Kind.values:
        raise Http404
    DataRequest.objects.create(organisation=_org(request), profile=profile, kind=kind)
    messages.success(request, "Request recorded. A staff member will follow up.")
    return redirect("me")


def _span_crop(span):
    """Where a passage sits on the rendered page, so a reviewer sees what a reader would see."""
    version = span.resume_version
    if span.page < 1 or span.page > len(version.page_sizes):
        return None
    for record in version.visible_spans:
        if record["start"] <= span.start and span.end <= record["end"]:
            x0, y0, x1, y1 = record["bbox"]
            width, height = version.page_sizes[span.page - 1]
            return {
                "url": f"/api/resumes/{version.pk}/pages/{span.page}/",
                "view_x": x0 - 2,
                "view_y": y0 - 2,
                "view_width": x1 - x0 + 4,
                "view_height": y1 - y0 + 4,
                "page_width": width,
                "page_height": height,
            }
    return None


@staff_only
def profile_list(request):
    errors = {}
    if request.method == "POST":
        resource_type = request.POST.get("resource_type", ResourceType.EXTERNAL)
        if resource_type not in ResourceType.values:
            raise Http404
        try:
            data = _clean_profile_post(request.POST)
            validate_profile(data, resource_type)
            profile = TalentProfile.objects.create(
                organisation=_org(request), resource_type=resource_type, **data
            )
            return redirect("profile-detail", pk=profile.pk)
        except ProfileInvalid as invalid:
            errors = invalid.errors
    profiles = TalentProfile.objects.for_org(_org(request)).filter(archived_at__isnull=True)
    any_profiles = profiles.exists()
    q = request.GET.get("q", "").strip()
    if q:
        profiles = profiles.filter(Q(display_name__icontains=q) | Q(title__icontains=q))
    resource_type = request.GET.get("resource_type") or ""
    if resource_type in ResourceType.values:
        profiles = profiles.filter(resource_type=resource_type)
    # A grouped query ignores the model's default order, so it is stated here.
    profiles = profiles.annotate(
        to_review=Count("spans", filter=Q(spans__state=SpanState.PROVISIONAL))
    ).order_by("display_name", "id")
    page, query = _paginate(request, profiles)
    context = {
        "page": page,
        "query": query,
        "q": q,
        "resource_type": resource_type,
        "type_choices": ResourceType.choices,
        "any_profiles": any_profiles,
        "errors": errors,
        "open_form": bool(errors),
        "form": request.POST if request.method == "POST" else None,
        "selected_type": request.POST.get("resource_type", ResourceType.EXTERNAL),
    }
    return render(request, "web/profile_list.html", context)


@staff_only
def profile_edit(request, pk):
    """Staff correct a profile, including allocation and availability."""
    profile = _get(TalentProfile, request, pk=pk)
    errors = {}
    if request.method == "POST":
        resource_type = request.POST.get("resource_type", profile.resource_type)
        if resource_type not in ResourceType.values:
            raise Http404
        try:
            data = _clean_profile_post(request.POST)
            validate_profile(data, resource_type)
            for field, value in data.items():
                setattr(profile, field, value)
            profile.resource_type = resource_type
            profile.save()
            messages.success(request, "Profile saved. Past runs keep the details they ran with.")
            return redirect("profile-detail", pk=profile.pk)
        except ProfileInvalid as invalid:
            errors = invalid.errors
    context = {
        "profile": profile,
        "form": request.POST if request.method == "POST" else None,
        "errors": errors,
        "type_choices": ResourceType.choices,
    }
    return render(request, "web/profile_edit.html", context)


@staff_only
def profile_detail(request, pk):
    profile = _get(TalentProfile, request, pk=pk)
    spans = list(
        profile.spans.select_related("skill", "resume_version").order_by(
            "resume_version__version", "start"
        )
    )
    context = {
        "profile": profile,
        "claims": profile.claims.select_related("skill"),
        "resumes": profile.resumes.order_by("-version"),
        "spans": [{"span": span, "crop": _span_crop(span)} for span in spans],
        "skills": SkillNode.objects.all(),
        "methods": [Method.TEST, Method.INTERVIEW],
        "decisions": ReviewDecision.objects.for_org(_org(request))
        .filter(profile=profile)
        .select_related("actor", "skill")
        .order_by("-created_at", "-pk")[:50],
        "open_requests": profile.datarequest_set.filter(resolved_at__isnull=True),
    }
    return render(request, "web/profile_detail.html", context)


@staff_only
@require_POST
def profile_upload(request, pk):
    profile = _get(TalentProfile, request, pk=pk)
    _upload_and_report(request, profile)
    return redirect("profile-detail", pk=profile.pk)


@staff_only
@require_POST
def profile_decide(request, pk):
    profile = _get(TalentProfile, request, pk=pk)
    organisation = _org(request)
    outcome = request.POST.get("outcome", "")
    reason = request.POST.get("reason", "")
    try:
        if outcome in (Outcome.ACCEPT, Outcome.EXCLUDE):
            span = span_for(organisation, profile, request.POST.get("span_id"))
            if span is None:
                raise Http404
            decide_span(
                span,
                outcome,
                reason,
                request.user,
                organisation,
                request.POST.get("months"),
            )
        else:
            skill_id = request.POST.get("skill_id", "")
            skill = SkillNode.objects.filter(pk=skill_id).first() if skill_id.isdigit() else None
            if skill is None:
                raise ReviewRefused("Pick a skill.")
            record_skill_decision(
                profile,
                skill,
                outcome,
                reason,
                request.user,
                organisation,
                request.POST.get("method", ""),
            )
        messages.success(request, "Decision recorded.")
    except ReviewRefused as refused:
        messages.error(request, str(refused))
    return redirect("profile-detail", pk=profile.pk)


@staff_only
@require_GET
def data_requests(request):
    open_requests = (
        DataRequest.objects.for_org(_org(request))
        .filter(resolved_at__isnull=True)
        .select_related("profile")
        .order_by("created_at", "pk")
    )
    page, query = _paginate(request, open_requests)
    return render(request, "web/data_requests.html", {"page": page, "query": query})


@staff_only
@require_POST
def data_request_resolve(request, pk):
    """Mark a person's requests handled. Acting on a deletion stays a deliberate human step."""
    profile = _get(TalentProfile, request, pk=pk)
    handled = (
        DataRequest.objects.for_org(_org(request))
        .filter(profile=profile, resolved_at__isnull=True)
        .update(resolved_at=timezone.now())
    )
    messages.success(request, f"{handled} request(s) marked as handled.")
    return redirect("data-requests")


@staff_only
@require_GET
def xray(request, pk):
    version = _get(ResumeVersion, request, pk=pk)
    audits = list(HiddenSpanAudit.objects.for_org(_org(request)).filter(resume_version=version))
    pages = []
    for number, size in enumerate(version.page_sizes, start=1):
        pages.append(
            {
                "number": number,
                "width": size[0],
                "height": size[1],
                "boxes": [
                    {
                        "x": a.bbox[0],
                        "y": a.bbox[1],
                        "width": a.bbox[2] - a.bbox[0],
                        "height": a.bbox[3] - a.bbox[1],
                        "vector": a.vector,
                    }
                    for a in audits
                    if a.page == number and a.bbox and not a.note_only
                ],
            }
        )
    context = {"version": version, "audits": audits, "pages": pages, "profile": version.profile}
    return render(request, "web/xray.html", context)


@staff_only
def project_list(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        allocation = request.POST.get("required_allocation_pct") or "100"
        if name and allocation.isdigit() and 1 <= int(allocation) <= 100:
            project = Project.objects.create(
                organisation=_org(request),
                name=name,
                description=request.POST.get("description", ""),
                start_date=_date_or_blank(request.POST.get("start_date")) or None,
                required_allocation_pct=int(allocation),
                created_by=request.user,
            )
            return redirect("project-detail", pk=project.pk)
        messages.error(request, "Enter a project name, and an allocation from 1 to 100.")
    projects = Project.objects.for_org(_org(request))
    return render(request, "web/project_list.html", {"projects": projects})


@staff_only
@require_GET
def project_detail(request, pk):
    project = _get(Project, request, pk=pk)
    context = {
        "project": project,
        "rubric": project.latest_rubric(),
        "rubrics": project.rubrics.order_by("-version"),
        "runs": project.runs.all(),
        "skills": SkillNode.objects.all(),
        "importance_choices": Importance.choices,
        "can_approve": request.membership.role in RUBRIC_APPROVER_ROLES,
        "run_key": uuid.uuid4(),
    }
    return render(request, "web/project_detail.html", context)


@staff_only
def project_edit(request, pk):
    project = _get(Project, request, pk=pk)
    if project.is_closed:
        messages.error(request, "This project is closed.")
        return redirect("project-detail", pk=pk)
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        allocation = request.POST.get("required_allocation_pct") or "100"
        if name and allocation.isdigit() and 1 <= int(allocation) <= 100:
            project.name = name
            project.description = request.POST.get("description", "")
            project.start_date = _date_or_blank(request.POST.get("start_date")) or None
            project.required_allocation_pct = int(allocation)
            project.save()
            messages.success(request, "Project saved. Past runs keep the dates they ran with.")
            return redirect("project-detail", pk=pk)
        messages.error(request, "Enter a project name, and an allocation from 1 to 100.")
    return render(request, "web/project_edit.html", {"project": project})


def _rubric_item(project, item_id):
    item = (
        RequirementSkill.objects.filter(pk=item_id, rubric__project=project)
        .select_related("rubric__project__organisation")
        .first()
    )
    if item is None:
        raise Http404
    return item


@staff_only
@require_POST
def project_skill_edit(request, pk, item_id):
    project, is_open = _open_project(request, pk)
    item = _rubric_item(project, item_id)
    if is_open:
        try:
            update_skill(
                item,
                _optional_int(request.POST.get("weight")) or 0,
                request.POST.get("importance") or item.importance,
                _optional_int(request.POST.get("required_months")) or 0,
                request.user,
            )
            messages.success(request, f"{item.skill.canonical_name} updated.")
        except RubricInvalid as invalid:
            messages.error(request, invalid.message)
        except RubricLocked:
            messages.error(request, LOCKED_MESSAGE)
        except ValueError:
            messages.error(request, "Enter whole numbers for weight and months.")
    return redirect("project-detail", pk=pk)


@staff_only
@require_POST
def project_skill_remove(request, pk, item_id):
    project, is_open = _open_project(request, pk)
    item = _rubric_item(project, item_id)
    if is_open:
        name = item.skill.canonical_name
        try:
            item.delete()
            messages.success(request, f"{name} removed from the draft.")
        except RubricLocked:
            messages.error(request, LOCKED_MESSAGE)
    return redirect("project-detail", pk=pk)


def _open_project(request, pk):
    project = _get(Project, request, pk=pk)
    if project.is_closed:
        messages.error(request, "This project is closed.")
        return project, False
    return project, True


@staff_only
@require_POST
def project_add_skill(request, pk):
    project, is_open = _open_project(request, pk)
    if is_open:
        try:
            add_skill(
                next_version(project),
                request.POST.get("skill", ""),
                request.POST.get("importance", ""),
                _optional_int(request.POST.get("weight")) or 0,
                _optional_int(request.POST.get("required_months")) or 0,
            )
        except (RubricInvalid, RubricLocked, ValueError) as error:
            messages.error(request, getattr(error, "message", "Check the weight and months."))
    return redirect("project-detail", pk=pk)


@_member(RUBRIC_APPROVER_ROLES)
@require_POST
def project_approve(request, pk):
    project, is_open = _open_project(request, pk)
    if is_open:
        rubric = project.latest_rubric()
        try:
            if rubric is None:
                raise RubricInvalid("A rubric needs at least one skill before approval.")
            approve_rubric(rubric, request.user)
            messages.success(request, f"Rubric v{rubric.version} approved and locked.")
        except RubricInvalid as invalid:
            messages.error(request, invalid.message)
        except RubricLocked:
            messages.error(request, "This version is already approved.")
    return redirect("project-detail", pk=pk)


@staff_only
@require_POST
def project_revise(request, pk):
    project, is_open = _open_project(request, pk)
    if is_open:
        next_version(project)
    return redirect("project-detail", pk=pk)


@staff_only
@require_POST
def project_close(request, pk):
    project = _get(Project, request, pk=pk)
    project.status = ProjectStatus.CLOSED
    project.save(update_fields=["status"])
    return redirect("project-detail", pk=pk)


@staff_only
@require_POST
def project_run(request, pk):
    project = _get(Project, request, pk=pk)
    try:
        run, _created = create_run(
            project, request.POST.get("key", ""), {}, request.user, _org(request)
        )
    except (RunRefused, IdempotencyConflict) as refused:
        messages.error(request, str(refused) or "This run request was already used.")
        return redirect("project-detail", pk=pk)
    return redirect("shortlist", pk=run.pk)


def _filters(request):
    group = request.GET.get("group") or None
    resource_type = request.GET.get("resource_type") or None
    if group not in (None, *dict(GROUPS)):
        group = None
    if resource_type not in (None, *ResourceType.values):
        resource_type = None
    return group, resource_type


def _next_step(result, contributions):
    """The specific blockers beside a candidate, and what a reviewer should do about them."""
    blockers = [c for c in contributions if c.importance == "REQUIRED" and c.bucket != "matched"]
    needs = ", ".join(f"{c.skill.canonical_name} ({c.label})" for c in blockers)
    if result.review_group == "READY":
        return "", "Open the evidence"
    if result.review_group == "UNMET":
        return "A reviewer recorded a must-have as not met.", "See the decision"
    if any(c.label == "Provisional" for c in contributions):
        return (f"Needs: {needs}" if needs else result.group_reason), "Review evidence"
    return (f"Needs: {needs}" if needs else result.group_reason), "Ask for evidence"


@staff_only
@require_GET
def shortlist(request, pk):
    run = _get(MatchRun, request, pk=pk)
    group, resource_type = _filters(request)
    q = request.GET.get("q", "").strip()
    with_evidence = request.GET.get("evidence") == "1"
    results = filtered_results(run, group, resource_type, q, with_evidence).prefetch_related(
        "contributions__skill"
    )
    page, query = _paginate(request, results)
    groups = []
    for key, label in GROUPS:
        rows = []
        for result in page:
            if result.review_group != key:
                continue
            contributions = list(result.contributions.all())
            needs, action = _next_step(result, contributions)
            rows.append({"result": result, "needs": needs, "action": action})
        if rows:
            groups.append({"key": key, "label": label, "rows": rows})
    tab_counts = dashboard_totals(run, None, resource_type, q, with_evidence)
    tabs_query = request.GET.copy()
    tabs_query.pop("page", None)
    tabs_query.pop("group", None)
    context = {
        "run": run,
        "project": run.project,
        "groups": groups,
        "page": page,
        "query": query,
        "tabs": [{"key": key, "label": label, "count": tab_counts[key]} for key, label in GROUPS],
        "tabs_total": tab_counts["total"],
        "tabs_query": tabs_query.urlencode(),
        "export_query": query,
        "any_results": page.paginator.count > 0,
        "total": page.paginator.count,
        "note": SCORE_NOTE,
        "group": group,
        "resource_type": resource_type,
        "q": q,
        "with_evidence": with_evidence,
        "type_choices": ResourceType.choices,
        "is_latest": latest_completed_run(run.project) == run,
    }
    return render(request, "web/shortlist.html", context)


@staff_only
@require_GET
def result_detail(request, pk):
    """The evidence drawer: a fragment for htmx, a full page without JavaScript."""
    result = _get(MatchResult, request, pk=pk)
    context = {
        "result": result,
        "run": result.run,
        "contributions": result.contributions.select_related("skill", "evidence_span"),
        "later": later_changes(result),
        "note": SCORE_NOTE,
        "resumes": result.profile.resumes.order_by("-version"),
    }
    template = "web/_evidence.html" if request.headers.get("HX-Request") else "web/result.html"
    return render(request, template, context)


@staff_only
@require_GET
def bench(request):
    consultants = TalentProfile.objects.for_org(_org(request)).filter(
        resource_type=ResourceType.INTERNAL, archived_at__isnull=True
    )
    free_by = _date_or_blank(request.GET.get("free_by"))
    if free_by:
        consultants = consultants.filter(available_from__lte=free_by)
    max_allocation = request.GET.get("max_allocation") or ""
    if max_allocation.isdigit():
        consultants = consultants.filter(allocation_pct__lte=int(max_allocation))
    context = {"consultants": consultants, "free_by": free_by, "max_allocation": max_allocation}
    return render(request, "web/bench.html", context)


@staff_only
@require_GET
def dashboard(request):
    organisation = _org(request)
    rows = []
    ready_total = 0
    for project in Project.objects.for_org(organisation):
        run = latest_completed_run(project)
        totals = dashboard_totals(run) if run else None
        ready_total += totals["READY"] if totals else 0
        rows.append({"project": project, "run": run, "totals": totals})
    to_review = (
        EvidenceSpan.objects.for_org(organisation).filter(state=SpanState.PROVISIONAL).count()
    )
    open_requests = (
        DataRequest.objects.for_org(organisation).filter(resolved_at__isnull=True).count()
    )
    queued = (
        ImportRow.objects.for_org(organisation)
        .filter(state=RowState.QUEUED, batch__status=BatchStatus.CONFIRMED)
        .count()
    )
    context = {
        "rows": rows,
        "note": SCORE_NOTE,
        "ready_total": ready_total,
        "to_review": to_review,
        "open_requests": open_requests,
        "queued": queued,
        "can_import": request.membership.role in IMPORT_ROLES,
    }
    return render(request, "web/dashboard.html", context)


@staff_only
@require_GET
def utilisation(request):
    organisation = _org(request)
    consultants = TalentProfile.objects.for_org(organisation).filter(
        resource_type=ResourceType.INTERNAL, archived_at__isnull=True
    )
    context = {"summary": utilisation_summary(organisation), "consultants": consultants}
    return render(request, "web/utilisation.html", context)


importer_only = _member(IMPORT_ROLES)


@importer_only
def import_list(request):
    if request.method == "POST":
        uploaded = request.FILES.get("file")
        source = request.POST.get("source_system", "").strip()
        if uploaded is None or not source:
            messages.error(request, "Choose a file and name its source system.")
        else:
            try:
                batch = preview_import(
                    uploaded.name,
                    uploaded.read(),
                    source,
                    _org(request),
                    request.user,
                    strict=False,
                )
                return redirect("import-detail", pk=batch.pk)
            except ImportInvalid as invalid:
                messages.error(request, str(invalid))
    batches = ImportBatch.objects.for_org(_org(request))
    return render(request, "web/import_list.html", {"batches": batches})


@importer_only
@require_GET
def import_detail(request, pk):
    batch = _get(ImportBatch, request, pk=pk)
    mapped = batch.mapping
    columns = [
        {"index": index, "header": header, "field": mapped.get(header, "")}
        for index, header in enumerate(source_headers(batch))
    ]
    context = {
        "batch": batch,
        "rows": batch.rows.all(),
        "changes": batch.changes.all()[:200],
        "columns": columns,
        "field_choices": [(field, FIELD_LABELS[field]) for field in MAPPABLE_FIELDS],
        "complete": mapping_is_complete(mapped),
    }
    return render(request, "web/import_detail.html", context)


@importer_only
@require_POST
def import_mapping(request, pk):
    batch = _get(ImportBatch, request, pk=pk)
    mapping = {}
    for index, header in enumerate(source_headers(batch)):
        field = request.POST.get(f"map_{index}", "")
        if field:
            mapping[header] = field
    try:
        remap_import(batch, mapping)
        messages.success(request, "Mapping updated. Check the rows below before you confirm.")
    except ImportInvalid as invalid:
        messages.error(request, str(invalid))
    return redirect("import-detail", pk=pk)


@importer_only
@require_POST
def import_confirm(request, pk):
    batch = _get(ImportBatch, request, pk=pk)
    try:
        confirm_import(batch)
    except ImportInvalid as invalid:
        messages.error(request, str(invalid))
    return redirect("import-detail", pk=pk)


@importer_only
@require_POST
def import_rollback(request, pk):
    batch = _get(ImportBatch, request, pk=pk)
    try:
        report = rollback_import(batch)
        messages.success(
            request,
            f"Rolled back: {report['reverted']} fields reverted, {report['archived']} profiles "
            f"archived, {report['kept_later_edits']} later edits kept.",
        )
    except ImportInvalid as invalid:
        messages.error(request, str(invalid))
    return redirect("import-detail", pk=pk)


@importer_only
@require_GET
def import_queue(request):
    rows = (
        ImportRow.objects.for_org(_org(request))
        .filter(state=RowState.QUEUED, batch__status=BatchStatus.CONFIRMED)
        .select_related("candidate_profile")
    )
    return render(request, "web/import_queue.html", {"rows": rows})


@importer_only
@require_POST
def import_queue_resolve(request, pk):
    row = _get(ImportRow, request, pk=pk)
    try:
        resolve_queue_row(row, request.POST.get("action", ""))
    except ImportInvalid as invalid:
        messages.error(request, str(invalid))
    return redirect("import-queue")
