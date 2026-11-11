"""Test-only URLconf: the real routes plus exactly one route the registry has never heard of."""

from django.http import HttpResponse
from django.urls import path

from config.urls import urlpatterns as real_urlpatterns

DUMMY_ROUTE = "api/dummy-unregistered/<int:pk>/"


def dummy_view(request, pk):
    return HttpResponse(f"object {pk}")


urlpatterns = [*real_urlpatterns, path(DUMMY_ROUTE, dummy_view)]
