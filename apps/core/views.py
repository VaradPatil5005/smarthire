from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def healthz(request: HttpRequest) -> JsonResponse:
    """Liveness probe. Reveals nothing about tenants, configuration or versions."""
    return JsonResponse({"status": "ok"})
