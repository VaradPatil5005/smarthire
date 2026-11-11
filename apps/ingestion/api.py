from django.http import FileResponse, Http404
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api import HasMembership, IsStaffRole, get_for_org, org_of
from apps.talent.api import own_profile, upload_summary
from apps.talent.models import TalentProfile
from apps.tenancy.models import Role

from .models import HiddenSpanAudit, ResumeVersion
from .services import UploadRefused, candidate_status, file_path, preview_path, receive_upload


def served_pdf(version):
    """The authorised way out. Always a download, under a name the server chose."""
    response = FileResponse(
        file_path(version).open("rb"),
        content_type="application/pdf",
        as_attachment=True,
        filename=f"resume-v{version.version}.pdf",
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


def version_for_request(request, pk):
    """A candidate reaches only their own versions. Anything else is 404."""
    version = get_for_org(ResumeVersion.objects.select_related("profile"), org_of(request), pk=pk)
    if request.membership.role == Role.CANDIDATE and version.profile.owner_id != request.user.pk:
        raise Http404
    return version


def audit_body(audit):
    return {
        "id": str(audit.pk),
        "page": audit.page,
        "bbox": audit.bbox,
        "vector": audit.vector,
        "field_name": audit.field_name,
        "text": audit.text,
        "true_length": audit.true_length,
        "note_only": audit.note_only,
        "disposition": audit.disposition,
        "weight": 0,
    }


class MeResumesView(APIView):
    permission_classes = [HasMembership]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = None

    def get(self, request):
        profile = own_profile(request)
        if profile is None:
            raise Http404
        return Response(upload_summary(profile))

    def post(self, request):
        profile = own_profile(request)
        if profile is None:
            raise Http404
        try:
            version = receive_upload(
                request.FILES.get("file"), profile, org_of(request), request.user
            )
        except UploadRefused as refused:
            return Response({"detail": str(refused)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"id": str(version.pk), "version": version.version, "status": "PENDING"},
            status=status.HTTP_202_ACCEPTED,
        )


class ProfileResumesView(APIView):
    """Staff upload on behalf of a profile, for example a bench consultant's résumé."""

    permission_classes = [IsStaffRole]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = None

    def post(self, request, pk):
        profile = get_for_org(TalentProfile.objects, org_of(request), pk=pk)
        try:
            version = receive_upload(
                request.FILES.get("file"), profile, org_of(request), request.user
            )
        except UploadRefused as refused:
            return Response({"detail": str(refused)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"id": str(version.pk), "version": version.version, "status": version.status},
            status=status.HTTP_202_ACCEPTED,
        )


class ResumeDetailView(APIView):
    """This is the scan job's result route. Candidates see no difference for a flagged file."""

    permission_classes = [HasMembership]
    serializer_class = None

    def get(self, request, pk):
        version = version_for_request(request, pk)
        body = {
            "id": str(version.pk),
            "version": version.version,
            "recovery_message": version.recovery_message,
            "status": candidate_status(version),
        }
        if request.membership.is_staff_role:
            body["status"] = version.status
            body["scanned_pages"] = version.scanned_pages
        return Response(body)


class ResumeDownloadView(APIView):
    permission_classes = [HasMembership]
    serializer_class = None

    def get(self, request, pk):
        version = version_for_request(request, pk)
        if not version.is_servable:
            raise Http404
        return served_pdf(version)


class ResumeXrayView(APIView):
    """Reviewer-only. Output is JSON, and the screens auto-escape it."""

    permission_classes = [IsStaffRole]
    serializer_class = None

    def get(self, request, pk):
        version = get_for_org(ResumeVersion.objects, org_of(request), pk=pk)
        audits = HiddenSpanAudit.objects.for_org(org_of(request)).filter(resume_version=version)
        return Response(
            {
                "id": str(version.pk),
                "status": version.status,
                "strip_counts": version.strip_counts,
                "audits": [audit_body(a) for a in audits],
            }
        )


class ResumePageImageView(APIView):
    """A rendered page, made by the worker at scan time and served only to staff."""

    permission_classes = [IsStaffRole]
    serializer_class = None

    def get(self, request, pk, page):
        version = get_for_org(ResumeVersion.objects, org_of(request), pk=pk)
        if not version.is_servable:
            raise Http404
        path = preview_path(version, page)
        if not path.exists():
            raise Http404
        response = FileResponse(path.open("rb"), content_type="image/png")
        response["X-Content-Type-Options"] = "nosniff"
        return response
