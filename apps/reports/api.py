from django.http import HttpResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api import IsStaffRole, get_for_org, org_of
from apps.matching.models import MatchRun

from .services import dashboard_totals, export_csv, export_xlsx, utilisation_summary

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _filters(request):
    params = request.query_params
    return (
        params.get("group"),
        params.get("resource_type"),
        params.get("q"),
        params.get("evidence") == "1",
    )


class RunDashboardView(APIView):
    permission_classes = [IsStaffRole]
    serializer_class = None

    def get(self, request, pk):
        run = get_for_org(MatchRun.objects, org_of(request), pk=pk)
        return Response(dashboard_totals(run, *_filters(request)))


class RunExportCsvView(APIView):
    """Same filters and permissions as the screen."""

    permission_classes = [IsStaffRole]
    serializer_class = None

    def get(self, request, pk):
        run = get_for_org(MatchRun.objects, org_of(request), pk=pk)
        response = HttpResponse(export_csv(run, *_filters(request)), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="shortlist-{run.pk}.csv"'
        return response


class RunExportXlsxView(APIView):
    permission_classes = [IsStaffRole]
    serializer_class = None

    def get(self, request, pk):
        run = get_for_org(MatchRun.objects, org_of(request), pk=pk)
        response = HttpResponse(export_xlsx(run, *_filters(request)), content_type=XLSX_TYPE)
        response["Content-Disposition"] = f'attachment; filename="shortlist-{run.pk}.xlsx"'
        return response


class UtilisationView(APIView):
    permission_classes = [IsStaffRole]
    serializer_class = None

    def get(self, request):
        return Response(utilisation_summary(org_of(request)))
