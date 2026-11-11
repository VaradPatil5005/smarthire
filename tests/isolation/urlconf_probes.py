"""Test-only URLconf: one view for each way a cross-tenant request can go right or wrong.

Every view treats OWNER_USERNAME as the organisation that owns the object.
"""

from django.http import (
    Http404,
    HttpResponse,
    HttpResponseForbidden,
    HttpResponseNotFound,
    HttpResponseRedirect,
    HttpResponseServerError,
)
from django.urls import path
from django.views import View
from django.views.decorators.http import require_GET

ORG_B_MARKER = "ORG-B-MARKER"
OWNER_USERNAME = "probe-owner"


def _is_owner(request):
    return request.user.username == OWNER_USERNAME


def _owned(request):
    return HttpResponse(ORG_B_MARKER)


def correctly_hidden(request):
    if _is_owner(request):
        return _owned(request)
    raise Http404


@require_GET
def correctly_hidden_get_only(request):
    return correctly_hidden(request)


def leaks_data(request):
    return _owned(request)


def forbidden(request):
    return _owned(request) if _is_owner(request) else HttpResponseForbidden()


def redirects(request):
    return _owned(request) if _is_owner(request) else HttpResponseRedirect("/elsewhere/")


def server_error(request):
    return _owned(request) if _is_owner(request) else HttpResponseServerError()


def not_found_but_leaks(request):
    return _owned(request) if _is_owner(request) else HttpResponseNotFound(ORG_B_MARKER)


def post_leaks(request):
    return correctly_hidden(request) if request.method == "GET" else _owned(request)


def options_leaks(request):
    return _owned(request) if request.method == "OPTIONS" else correctly_hidden(request)


def bare_405_without_allow_header(request):
    return correctly_hidden(request) if request.method == "GET" else HttpResponse(status=405)


class DeleteForbidden(View):
    """Declares DELETE in its Allow header, then answers another organisation with 403."""

    def get(self, request):
        return correctly_hidden(request)

    def delete(self, request):
        return HttpResponseForbidden()


def always_404(request):
    raise Http404


def owner_response_has_no_marker(request):
    if _is_owner(request):
        return HttpResponse("nothing identifying")
    raise Http404


def owner_gets_403(request):
    return HttpResponseForbidden()


urlpatterns = [
    path("probe/correctly-hidden/", correctly_hidden),
    path("probe/correctly-hidden-get-only/", correctly_hidden_get_only),
    path("probe/leaks-data/", leaks_data),
    path("probe/forbidden/", forbidden),
    path("probe/redirects/", redirects),
    path("probe/server-error/", server_error),
    path("probe/not-found-but-leaks/", not_found_but_leaks),
    path("probe/post-leaks/", post_leaks),
    path("probe/options-leaks/", options_leaks),
    path("probe/bare-405/", bare_405_without_allow_header),
    path("probe/delete-forbidden/", DeleteForbidden.as_view()),
    path("probe/always-404/", always_404),
    path("probe/owner-no-marker/", owner_response_has_no_marker),
    path("probe/owner-gets-403/", owner_gets_403),
]
