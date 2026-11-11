from django.http import Http404
from rest_framework import serializers, status
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api import HasMembership, IsStaffRole, org_of
from apps.ingestion.services import candidate_status
from apps.tenancy.models import Role

from .models import DataRequest, ResourceType, SkillClaim, TalentProfile
from .services import MAX_NOTICE_DAYS, ProfileInvalid, add_form_claim, validate_profile

CORRECTION_ROUTE = {
    "edit_profile": "/api/profiles/me/",
    "add_skill": "/api/profiles/me/claims/",
    "upload_new_version": "/api/profiles/me/resumes/",
    "data_request": "/api/profiles/me/data-requests/",
}


class SkillClaimSerializer(serializers.ModelSerializer):
    skill = serializers.CharField(source="skill.canonical_name", read_only=True)

    class Meta:
        model = SkillClaim
        fields = ["id", "skill", "provenance", "months", "confirmed"]
        read_only_fields = fields


class ProfileSerializer(serializers.ModelSerializer):
    claims = SkillClaimSerializer(many=True, read_only=True)
    allocation_pct = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=100
    )
    notice_days = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=MAX_NOTICE_DAYS
    )

    class Meta:
        model = TalentProfile
        fields = [
            "id",
            "resource_type",
            "display_name",
            "title",
            "email",
            "phone",
            "college",
            "allocation_pct",
            "available_from",
            "notice_days",
            "source_system",
            "external_id",
            "claims",
        ]
        read_only_fields = ["id", "source_system", "external_id", "claims"]

    def validate(self, attrs):
        merged = {}
        if self.instance:
            merged = {f: getattr(self.instance, f) for f in ("title", "display_name")}
            merged["allocation_pct"] = self.instance.allocation_pct
            merged["available_from"] = self.instance.available_from
        merged.update(attrs)
        resource_type = attrs.get(
            "resource_type",
            self.instance.resource_type if self.instance else ResourceType.EXTERNAL,
        )
        try:
            validate_profile(merged, resource_type)
        except ProfileInvalid as invalid:
            raise serializers.ValidationError(invalid.errors) from invalid
        return attrs


class CandidateProfileSerializer(ProfileSerializer):
    """A candidate's own view: bench fields and the resource type are not theirs to set."""

    # Declared fields ignore Meta.read_only_fields, so these must be overridden here.
    allocation_pct = serializers.IntegerField(read_only=True)

    class Meta(ProfileSerializer.Meta):
        read_only_fields = [
            "id",
            "resource_type",
            "allocation_pct",
            "available_from",
            "source_system",
            "external_id",
            "claims",
        ]


def own_profile(request):
    return (
        TalentProfile.objects.for_org(org_of(request))
        .filter(owner=request.user, archived_at__isnull=True)
        .first()
    )


def upload_summary(profile):
    return [
        {
            "id": str(version.pk),
            "version": version.version,
            "status": candidate_status(version),
            "recovery_message": version.recovery_message,
        }
        for version in profile.resumes.order_by("-version")
    ]


class MeView(APIView):
    """A candidate's own profile. Any organisation or role in the payload is ignored."""

    permission_classes = [HasMembership]
    serializer_class = CandidateProfileSerializer

    def _body(self, profile):
        return {
            **CandidateProfileSerializer(profile).data,
            "uploads": upload_summary(profile),
            "correction_route": CORRECTION_ROUTE,
        }

    def get(self, request):
        profile = own_profile(request)
        if profile is None:
            raise Http404
        return Response(self._body(profile))

    def post(self, request):
        if own_profile(request):
            return Response(
                {"detail": "You already have a profile."}, status=status.HTTP_409_CONFLICT
            )
        serializer = CandidateProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save(
            organisation=org_of(request), owner=request.user, resource_type=ResourceType.EXTERNAL
        )
        return Response(self._body(profile), status=status.HTTP_201_CREATED)

    def patch(self, request):
        profile = own_profile(request)
        if profile is None:
            raise Http404
        serializer = CandidateProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(self._body(profile))


class MeClaimsView(APIView):
    permission_classes = [HasMembership]
    serializer_class = SkillClaimSerializer

    def get(self, request):
        profile = own_profile(request)
        if profile is None:
            raise Http404
        return Response(SkillClaimSerializer(profile.claims.all(), many=True).data)

    def post(self, request):
        profile = own_profile(request)
        if profile is None:
            raise Http404
        try:
            claim = add_form_claim(
                profile, request.data.get("skill", ""), request.data.get("months")
            )
        except ProfileInvalid as invalid:
            return Response(invalid.errors, status=status.HTTP_400_BAD_REQUEST)
        return Response(SkillClaimSerializer(claim).data, status=status.HTTP_201_CREATED)


class MeDataRequestView(APIView):
    """Correction or deletion: recorded by ID for a staff role to act on."""

    permission_classes = [HasMembership]
    serializer_class = None

    def post(self, request):
        profile = own_profile(request)
        if profile is None:
            raise Http404
        kind = request.data.get("kind")
        if kind not in DataRequest.Kind.values:
            return Response({"kind": "Choose CORRECTION or DELETION."}, status=400)
        record = DataRequest.objects.create(
            organisation=org_of(request), profile=profile, kind=kind
        )
        return Response({"id": record.pk, "kind": kind}, status=status.HTTP_201_CREATED)


class ProfileListView(ListCreateAPIView):
    permission_classes = [IsStaffRole]
    serializer_class = ProfileSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TalentProfile.objects.none()
        return TalentProfile.objects.for_org(org_of(self.request)).filter(archived_at__isnull=True)

    def perform_create(self, serializer):
        serializer.save(organisation=org_of(self.request))


class ProfileDetailView(RetrieveUpdateAPIView):
    """Staff read and edit. A candidate reaches only their own; any other ID is 404."""

    permission_classes = [HasMembership]
    http_method_names = ["get", "patch", "head", "options"]
    serializer_class = ProfileSerializer

    def get_serializer_class(self):
        if getattr(self, "swagger_fake_view", False):
            return ProfileSerializer
        return (
            ProfileSerializer
            if self.request.membership.is_staff_role
            else CandidateProfileSerializer
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TalentProfile.objects.none()
        queryset = TalentProfile.objects.for_org(org_of(self.request))
        if self.request.membership.role == Role.CANDIDATE:
            queryset = queryset.filter(owner=self.request.user)
        return queryset
