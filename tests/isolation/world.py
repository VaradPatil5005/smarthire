"""Two organisations with a marked object of every kind, for the cross-tenant suite (T2.2)."""

import uuid
from dataclasses import dataclass

from django.conf import settings
from django.test import Client

from apps.ingestion.models import HiddenSpanAudit, ResumeStatus, ResumeVersion
from apps.ingestion.services import file_path, preview_path
from apps.matching.models import EvidenceSpan, MatchResult, MatchRun
from apps.matching.services import create_run
from apps.matching.vocabulary import latest_dictionary, load_seed_pack
from apps.onboarding.models import BatchStatus, ImportBatch, ImportRow, RowState
from apps.projects.models import Project
from apps.projects.services import next_version
from apps.tenancy.models import Role
from tests.factories.world import make_org, make_profile, make_project, make_user

A_MARKER = "ORGAMARKER"
B_MARKER = "ORGBMARKER"
_NEVER = uuid.UUID("00000000-0000-4000-8000-000000000000")


@dataclass
class Tenant:
    organisation: object
    admin: object
    candidate: object
    profile: object
    own_profile: object
    project: object
    draft_project: object
    resume: object
    run: object
    result: object
    batch: object
    queue_row: object

    def client(self, actor="staff"):
        client = Client()
        client.force_login(self.candidate if actor == "candidate" else self.admin)
        return client


def _resume(org, profile, marker):
    version_id = uuid.uuid4()
    version = ResumeVersion.objects.create(
        id=version_id,
        organisation=org,
        profile=profile,
        version=1,
        object_key=f"{org.pk}/{version_id}.pdf",
        sha256="0" * 64,
        size_bytes=9,
        status=ResumeStatus.FLAGGED,
        pages=1,
        page_sizes=[[595, 842]],
        visible_text=f"Led ENOVIA configuration {marker}",
        visible_spans=[{"page": 1, "bbox": [0, 0, 9, 9], "text": "x", "start": 0, "end": 1}],
    )
    path = file_path(version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7 fixture")
    preview = preview_path(version, 1)
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"\x89PNG fixture")
    HiddenSpanAudit.objects.create(
        organisation=org,
        resume_version=version,
        page=1,
        bbox=[0, 0, 9, 9],
        vector="LOW_CONTRAST",
        text=marker,
        true_length=len(marker),
    )
    skill = latest_dictionary().aliases.get(text="ENOVIA configuration").skill
    EvidenceSpan.objects.create(
        organisation=org,
        profile=profile,
        resume_version=version,
        skill=skill,
        page=1,
        start=4,
        end=24,
        quote="ENOVIA configuration",
        section="EXPERIENCE",
    )
    return version


def _tenant(marker):
    load_seed_pack()
    org = make_org(f"{marker} org")
    admin = make_user(org, Role.ADMIN)
    candidate = make_user(org, Role.CANDIDATE)
    profile = make_profile(org, name=f"{marker} person")
    own = make_profile(org, name=f"{marker} candidate", owner=candidate)
    project = make_project(org, approver=admin, name=f"{marker} project")
    draft = make_project(org, approved=False, name=f"{marker} draft")
    resume = _resume(org, profile, marker)
    run, _created = create_run(project, f"key-{marker}", {}, admin, org)
    result = run.results.get(profile=profile)
    batch = ImportBatch.objects.create(
        organisation=org,
        source_system=f"{marker} source",
        source_digest="0" * 64,
        status=BatchStatus.CONFIRMED,
    )
    queue_row = ImportRow.objects.create(
        organisation=org,
        batch=batch,
        row_number=1,
        row_hash="0" * 64,
        data={"display_name": marker},
        state=RowState.QUEUED,
        reason=marker,
        candidate_profile=profile,
    )
    return Tenant(
        org, admin, candidate, profile, own, project, draft, resume, run, result, batch, queue_row
    )


def build_world():
    return _tenant(A_MARKER), _tenant(B_MARKER)


def kwargs_for(kind, tenant):
    """URL parameters reaching this tenant's object of this kind."""
    if kind == "profile":
        return {"pk": tenant.profile.pk}
    if kind == "resume":
        return {"pk": tenant.resume.pk}
    if kind == "resume_page":
        return {"pk": tenant.resume.pk, "page": 1}
    if kind == "project":
        return {"pk": tenant.project.pk}
    if kind == "draft_project":
        return {"pk": tenant.draft_project.pk}
    if kind == "rubric":
        return {"pk": tenant.project.pk, "version": 1}
    if kind == "rubric_skill":
        item = tenant.draft_project.latest_rubric().skills.first()
        return {"pk": tenant.draft_project.pk, "version": 1, "item_id": item.pk}
    if kind == "run":
        return {"pk": tenant.run.pk}
    if kind == "result":
        return {"pk": tenant.result.pk}
    if kind == "batch":
        return {"pk": tenant.batch.pk}
    if kind == "queue_row":
        return {"pk": tenant.queue_row.pk}
    raise KeyError(kind)


def missing_kwargs(kwargs):
    """The same URL shape with IDs that have never existed."""
    missing = {}
    for name, value in kwargs.items():
        if name == "pk":
            missing[name] = _NEVER
        elif name == "item_id":
            missing[name] = 999_999_999
        else:
            missing[name] = value
    return missing


def private_media_is_outside_static():
    return not str(settings.PRIVATE_MEDIA_ROOT).startswith(str(settings.STATIC_ROOT))


__all__ = [
    "A_MARKER",
    "B_MARKER",
    "MatchResult",
    "MatchRun",
    "Project",
    "build_world",
    "kwargs_for",
    "missing_kwargs",
    "next_version",
]
