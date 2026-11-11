from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerSplitView

from apps.core.views import healthz

urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerSplitView.as_view(url_name="schema"), name="api-docs"),
    path("api/", include("config.api_urls")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.web.urls")),
]

if settings.ADMIN_ENABLED:
    urlpatterns.insert(0, path("admin/", admin.site.urls))
