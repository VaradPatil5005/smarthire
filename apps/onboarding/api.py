from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api import IsImporter, get_for_org, org_of

from .models import BatchStatus, ImportBatch, ImportRow, RowState
from .services import (
    ImportInvalid,
    confirm_import,
    preview_import,
    resolve_queue_row,
    rollback_import,
)


def batch_body(batch):
    return {
        "id": str(batch.pk),
        "status": batch.status,
        "source_system": batch.source_system,
        "source_digest": batch.source_digest,
        "mapping_version": batch.mapping_version,
        "mapping": batch.mapping,
        "insert_count": batch.insert_count,
        "update_count": batch.update_count,
        "unchanged_count": batch.unchanged_count,
        "withheld_count": batch.withheld_count,
        "queued_count": batch.queued_count,
        "rows": [
            {
                "row": row.row_number,
                "state": row.state,
                "reason": row.reason,
                "external_id": row.external_id,
            }
            for row in batch.rows.all()
        ],
        "changes": [
            {
                "profile": str(c.profile_id),
                "field": c.field,
                "previous": c.previous_value,
                "imported": c.imported_value,
                "at": c.changed_at,
            }
            for c in batch.changes.all()
        ],
    }


class ImportListView(APIView):
    permission_classes = [IsImporter]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = None

    @extend_schema(operation_id="imports_list")
    def get(self, request):
        batches = ImportBatch.objects.for_org(org_of(request))
        return Response(
            [{"id": str(b.pk), "status": b.status, "source": b.source_system} for b in batches]
        )

    def post(self, request):
        uploaded = request.FILES.get("file")
        source = (request.data.get("source_system") or "").strip()
        if uploaded is None or not source:
            return Response({"detail": "A file and a source system are required."}, status=400)
        try:
            batch = preview_import(
                uploaded.name, uploaded.read(), source, org_of(request), request.user
            )
        except ImportInvalid as invalid:
            return Response({"detail": str(invalid)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(batch_body(batch), status=status.HTTP_201_CREATED)


class ImportDetailView(APIView):
    permission_classes = [IsImporter]
    serializer_class = None

    def get(self, request, pk):
        return Response(batch_body(get_for_org(ImportBatch.objects, org_of(request), pk=pk)))


class ImportConfirmView(APIView):
    permission_classes = [IsImporter]
    serializer_class = None

    def post(self, request, pk):
        batch = get_for_org(ImportBatch.objects, org_of(request), pk=pk)
        try:
            return Response(batch_body(confirm_import(batch)))
        except ImportInvalid as invalid:
            return Response({"detail": str(invalid)}, status=status.HTTP_409_CONFLICT)


class ImportRollbackView(APIView):
    permission_classes = [IsImporter]
    serializer_class = None

    def post(self, request, pk):
        batch = get_for_org(ImportBatch.objects, org_of(request), pk=pk)
        try:
            return Response(rollback_import(batch))
        except ImportInvalid as invalid:
            return Response({"detail": str(invalid)}, status=status.HTTP_409_CONFLICT)


class ImportQueueView(APIView):
    permission_classes = [IsImporter]
    serializer_class = None

    def get(self, request):
        rows = (
            ImportRow.objects.for_org(org_of(request))
            .filter(state=RowState.QUEUED, batch__status=BatchStatus.CONFIRMED)
            .select_related("candidate_profile")
        )
        return Response(
            [
                {
                    "id": str(row.pk),
                    "row": row.row_number,
                    "reason": row.reason,
                    "incoming": row.data,
                    "existing": {
                        "id": str(row.candidate_profile_id),
                        "name": row.candidate_profile.display_name,
                    },
                }
                for row in rows
            ]
        )


class ImportQueueResolveView(APIView):
    permission_classes = [IsImporter]
    parser_classes = [JSONParser, FormParser]
    serializer_class = None

    def post(self, request, pk):
        row = get_for_org(ImportRow.objects, org_of(request), pk=pk)
        try:
            row = resolve_queue_row(row, request.data.get("action", ""))
        except ImportInvalid as invalid:
            return Response({"detail": str(invalid)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"id": str(row.pk), "state": row.state})
