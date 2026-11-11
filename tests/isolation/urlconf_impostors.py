"""Test-only URLconf: routes that look right to a shallow check but are not what they claim."""

from django.http import HttpResponse, HttpResponseRedirect
from django.urls import path, re_path


def impostor_of_healthz(request):
    return HttpResponse('{"status": "ok"}')


def plain_view_redirecting_to_login(request):
    return HttpResponseRedirect("/admin/login/?next=/admin/not-really-admin/")


def regex_view(request):
    return HttpResponse("regex")


def unnamed_group_view(request, value):
    return HttpResponse("unnamed")


urlpatterns = [
    path("healthz/", impostor_of_healthz),
    path("admin/not-really-admin/", plain_view_redirecting_to_login),
    re_path(r"^regex-top/$", regex_view),
    re_path(r"^regex-unnamed/(\d+)/$", unnamed_group_view),
]
