from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api import HasMembership, IsRubricApprover, IsStaffRole, get_for_org, org_of

from .models import Project, ProjectStatus, RubricLocked
from .services import RubricInvalid, add_skill, approve_rubric, next_version, update_skill_weight


class ProjectSerializer(serializers.ModelSerializer):
    required_allocation_pct = serializers.IntegerField(required=False, min_value=1, max_value=100)

    class Meta:
        model = Project
        fields = ["id", "name", "description", "status", "start_date", "required_allocation_pct"]
        read_only_fields = ["id", "status"]


def _rubric_body(rubric):
    return {
        "id": rubric.pk,
        "version": rubric.version,
        "status": rubric.status,
        "approved_by": rubric.approved_by_id,
        "approved_at": rubric.approved_at,
        "skills": [
            {
                "id": item.pk,
                "skill": item.skill.canonical_name,
                "importance": item.importance,
                "weight": item.weight,
                "required_months": item.required_months,
            }
            for item in rubric.skills.select_related("skill")
        ],
    }


def _project(request, pk):
    return get_for_org(Project.objects, org_of(request), pk=pk)


def _rubric(request, pk, version):
    rubric = _project(request, pk).rubrics.filter(version=version).first()
    if rubric is None:
        raise Http404
    return rubric


def _locked():
    return Response(
        {"detail": "Approved rubrics cannot change. Create the next version."},
        status=status.HTTP_409_CONFLICT,
    )


class ProjectListView(APIView):
    serializer_class = ProjectSerializer

    def get_permissions(self):
        return [IsStaffRole()]

    @extend_schema(operation_id="projects_list")
    def get(self, request):
        projects = Project.objects.for_org(org_of(request))
        return Response(ProjectSerializer(projects, many=True).data)

    def post(self, request):
        serializer = ProjectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project = serializer.save(organisation=org_of(request), created_by=request.user)
        return Response(ProjectSerializer(project).data, status=status.HTTP_201_CREATED)


class ProjectDetailView(APIView):
    serializer_class = ProjectSerializer

    def get_permissions(self):
        return [IsStaffRole()]

    def get(self, request, pk):
        return Response(ProjectSerializer(_project(request, pk)).data)

    def patch(self, request, pk):
        project = _project(request, pk)
        if project.is_closed:
            return Response({"detail": "This project is closed."}, status=status.HTTP_409_CONFLICT)
        serializer = ProjectSerializer(project, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ProjectCloseView(APIView):
    serializer_class = None

    def get_permissions(self):
        return [IsStaffRole()]

    def post(self, request, pk):
        project = _project(request, pk)
        project.status = ProjectStatus.CLOSED
        project.save(update_fields=["status"])
        return Response(ProjectSerializer(project).data)


class RubricListView(APIView):
    serializer_class = None

    def get_permissions(self):
        return [IsStaffRole()]

    @extend_schema(operation_id="projects_rubrics_list")
    def get(self, request, pk):
        rubrics = _project(request, pk).rubrics.all()
        return Response([_rubric_body(r) for r in rubrics])

    def post(self, request, pk):
        project = _project(request, pk)
        if project.is_closed:
            return Response({"detail": "This project is closed."}, status=status.HTTP_409_CONFLICT)
        return Response(_rubric_body(next_version(project)), status=status.HTTP_201_CREATED)


class RubricDetailView(APIView):
    serializer_class = None
    permission_classes = [HasMembership]

    def get_permissions(self):
        return [IsStaffRole()]

    def get(self, request, pk, version):
        return Response(_rubric_body(_rubric(request, pk, version)))


class RubricSkillsView(APIView):
    serializer_class = None

    def get_permissions(self):
        return [IsStaffRole()]

    def post(self, request, pk, version):
        rubric = _rubric(request, pk, version)
        if rubric.project.is_closed:
            return Response({"detail": "This project is closed."}, status=status.HTTP_409_CONFLICT)
        try:
            add_skill(
                rubric,
                request.data.get("skill", ""),
                request.data.get("importance", ""),
                request.data.get("weight"),
                request.data.get("required_months", 0),
            )
        except RubricLocked:
            return _locked()
        except RubricInvalid as invalid:
            return Response({"detail": invalid.message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_rubric_body(rubric), status=status.HTTP_201_CREATED)


class RubricSkillDetailView(APIView):
    serializer_class = None

    def get_permissions(self):
        return [IsStaffRole()]

    def _item(self, request, pk, version, item_id):
        item = _rubric(request, pk, version).skills.filter(pk=item_id).first()
        if item is None:
            raise Http404
        return item

    def patch(self, request, pk, version, item_id):
        item = self._item(request, pk, version, item_id)
        if item.rubric.project.is_closed:
            return Response({"detail": "This project is closed."}, status=status.HTTP_409_CONFLICT)
        try:
            update_skill_weight(item, request.data.get("weight"), request.user)
        except RubricLocked:
            return _locked()
        except RubricInvalid as invalid:
            return Response({"detail": invalid.message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_rubric_body(item.rubric))

    def delete(self, request, pk, version, item_id):
        item = self._item(request, pk, version, item_id)
        if item.rubric.project.is_closed:
            return Response({"detail": "This project is closed."}, status=status.HTTP_409_CONFLICT)
        try:
            item.delete()
        except RubricLocked:
            return _locked()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RubricApproveView(APIView):
    serializer_class = None

    def get_permissions(self):
        return [IsRubricApprover()]

    def post(self, request, pk, version):
        rubric = _rubric(request, pk, version)
        if rubric.project.is_closed:
            return Response({"detail": "This project is closed."}, status=status.HTTP_409_CONFLICT)
        try:
            rubric = approve_rubric(rubric, request.user)
        except RubricLocked:
            return _locked()
        except RubricInvalid as invalid:
            return Response({"detail": invalid.message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_rubric_body(rubric))
