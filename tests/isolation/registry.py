"""The isolation registry: every route in the app, classified, with the reason in words.

Adding a route without an entry here fails the build (test_route_registry.py). The registry is
keyed by the exact route string Django reports, one entry per route with no wildcards: a blanket
`admin/*` entry would let a tenant model registered in admin pass without anyone looking at it.

Each label is a claim the suite checks against the running app:

- TENANT_OBJECT: takes an object ID. Another organisation's ID must return 404 (AC-AUTH-09).
- TENANT_COLLECTION: lists or creates with no object ID, so there is no ID to guess. It must
  return and write only the membership's own rows (AC-AUTH-12, AC-AUTH-13).
- PUBLIC_NO_TENANT_DATA: pinned below by route and view. Answers GET with 200 whether signed in
  or not, serves no account data and writes nothing on POST. Every other api/ route must
  therefore be a tenant class, because OPERATOR_ADMIN is confined to admin/.
- OPERATOR_ADMIN: a view of Django admin, turned away unless is_staff. It is global and NOT
  tenant-scoped: staff see every organisation. Each model reason below says what that exposes.
  D-008 keeps tenant models out: ADMIN_CLASS_BY_MODEL pins what may be registered and its admin
  class, and no allowed admin may have inlines, since an inline would expose a model that is not
  registered. Any exception needs a DECISION entry and an organisation-scoped get_queryset.

The sub-routes are enumerated per model because that is how a reviewer sees what each one opens.
"""

from dataclasses import dataclass
from enum import Enum


class RouteClass(Enum):
    TENANT_OBJECT = "tenant object"
    TENANT_COLLECTION = "tenant collection"
    PUBLIC_NO_TENANT_DATA = "public, no tenant data"
    OPERATOR_ADMIN = "operator admin, global"
    SESSION_CONTROL = "signed-in control, serves no rows"


@dataclass(frozen=True)
class RouteEntry:
    route: str
    route_class: RouteClass
    reason: str
    object_kind: str | None = None
    # read: owner GET returns the marker. binary: owner GET is 200 with non-text content.
    # action: POST-only, so the owner's POST proves the object is reachable.
    control: str = "read"
    actor: str = "staff"
    has_marker: bool = True


@dataclass(frozen=True)
class PublicRouteContract:
    view: str
    post_status: int


PINNED_PUBLIC_ROUTES = {
    "healthz/": PublicRouteContract("apps.core.views.healthz", 405),
    "api/schema/": PublicRouteContract("drf_spectacular.views.SpectacularAPIView", 405),
    "api/docs/": PublicRouteContract("drf_spectacular.views.SpectacularSwaggerSplitView", 405),
    "login/": PublicRouteContract("apps.accounts.views.ThrottledLoginView", 200),
    "join/": PublicRouteContract("apps.accounts.views.join", 200),
    # A failed sign-in re-renders the form with 200 and creates no session.
    "admin/login/": PublicRouteContract("django.contrib.admin.sites.AdminSite.login", 200),
}

# D-008, by ModelAdmin class: a subclass could add inlines or widen get_queryset unnoticed.
ADMIN_CLASS_BY_MODEL = {
    "accounts.User": "django.contrib.auth.admin.UserAdmin",
    "auth.Group": "django.contrib.auth.admin.GroupAdmin",
    "django_q.Schedule": "django_q.admin.ScheduleAdmin",
    "django_q.Success": "django_q.admin.TaskAdmin",
    "django_q.Failure": "django_q.admin.FailAdmin",
    "django_q.OrmQ": "django_q.admin.QueueAdmin",
}
ADMIN_MODEL_ALLOW_LIST = frozenset(ADMIN_CLASS_BY_MODEL)

# The one admin route whose view carries neither admin_site nor model_admin, pinned by identity.
# UserAdmin wraps it with admin_view directly, which does not set those attributes.
OPERATOR_VIEWS_WITHOUT_ADMIN_ATTRIBUTES = {
    "admin/accounts/user/<id>/password/": (
        "django.contrib.auth.admin.UserAdmin.user_change_password"
    ),
}

_ADMIN_MODEL_SUFFIXES = (
    "",
    "add/",
    "<path:object_id>/history/",
    "<path:object_id>/delete/",
    "<path:object_id>/change/",
    "<path:object_id>/",
)


def _public(route, reason):
    return RouteEntry(route, RouteClass.PUBLIC_NO_TENANT_DATA, reason)


def _operator(route, reason):
    return RouteEntry(route, RouteClass.OPERATOR_ADMIN, reason)


def _admin_model(model_path, reason):
    return [_operator(f"admin/{model_path}/{suffix}", reason) for suffix in _ADMIN_MODEL_SUFFIXES]


_JOB_REASON = (
    "django-q2 job records for every organisation. Empty until background jobs arrive in T2.6; "
    "after that job arguments and results sit here unscoped, so T2.6 must keep résumé text and "
    "contact fields out of them."
)
_USER_REASON = "Every user account in every organisation. Not mounted in production (D-011)."


def _object(route, kind, control="read", **kwargs):
    return RouteEntry(
        route,
        RouteClass.TENANT_OBJECT,
        "Object route, 404 cross-tenant.",
        kind,
        control=control,
        **kwargs,
    )


def _collection(route, **kwargs):
    return RouteEntry(route, RouteClass.TENANT_COLLECTION, "Lists own rows only.", **kwargs)


def _control(route, reason):
    return RouteEntry(route, RouteClass.SESSION_CONTROL, reason)


_TENANT_ROUTES = [
    _collection("api/skills/", has_marker=False),
    _collection("api/profiles/me/", actor="candidate"),
    _collection("api/profiles/me/claims/", actor="candidate", has_marker=False),
    _collection("api/profiles/me/data-requests/", actor="candidate", has_marker=False),
    _collection("api/profiles/me/resumes/", actor="candidate", has_marker=False),
    _collection("api/profiles/"),
    _object("api/profiles/<uuid:pk>/", "profile"),
    _object("api/profiles/<uuid:pk>/resumes/", "profile", control="action"),
    _object("api/profiles/<uuid:pk>/evidence/", "profile", has_marker=False),
    _object("api/resumes/<uuid:pk>/", "resume", has_marker=False),
    _object("api/resumes/<uuid:pk>/download/", "resume", control="binary"),
    _object("api/resumes/<uuid:pk>/xray/", "resume"),
    _object("api/resumes/<uuid:pk>/pages/<int:page>/", "resume_page", control="binary"),
    _collection("api/projects/"),
    _object("api/projects/<uuid:pk>/", "project"),
    _object("api/projects/<uuid:pk>/close/", "project", control="action"),
    _object("api/projects/<uuid:pk>/rubrics/", "project", has_marker=False),
    _object("api/projects/<uuid:pk>/rubrics/<int:version>/", "rubric", has_marker=False),
    _object("api/projects/<uuid:pk>/rubrics/<int:version>/skills/", "rubric", control="action"),
    _object(
        "api/projects/<uuid:pk>/rubrics/<int:version>/skills/<int:item_id>/",
        "rubric_skill",
        control="action",
    ),
    _object("api/projects/<uuid:pk>/rubrics/<int:version>/approve/", "rubric", control="action"),
    _object("api/projects/<uuid:pk>/runs/", "project", has_marker=False),
    _object("api/runs/<uuid:pk>/", "run", has_marker=False),
    _object("api/runs/<uuid:pk>/results/", "run"),
    _object("api/runs/<uuid:pk>/reproduce/", "run", control="action"),
    _object("api/runs/<uuid:pk>/dashboard/", "run", has_marker=False),
    _object("api/runs/<uuid:pk>/export.csv", "run"),
    _object("api/runs/<uuid:pk>/export.xlsx", "run", control="binary"),
    _object("api/results/<uuid:pk>/reviews/", "result", control="action"),
    _collection("api/reports/utilisation/", has_marker=False),
    _collection("api/imports/", has_marker=False),
    _collection("api/imports/queue/"),
    _object("api/imports/queue/<uuid:pk>/resolve/", "queue_row", control="action"),
    _object("api/imports/<uuid:pk>/", "batch", has_marker=False),
    _object("api/imports/<uuid:pk>/confirm/", "batch", control="action"),
    _object("api/imports/<uuid:pk>/rollback/", "batch", control="action"),
    _collection("me/", actor="candidate"),
    _collection("me/skills/", actor="candidate", has_marker=False),
    _collection("me/upload/", actor="candidate", has_marker=False),
    _collection("me/data-request/", actor="candidate", has_marker=False),
    _collection("profiles/"),
    _object("profiles/<uuid:pk>/", "profile"),
    _object("profiles/<uuid:pk>/edit/", "profile"),
    _object("profiles/<uuid:pk>/requests/resolve/", "profile", control="action"),
    _collection("requests/", has_marker=False),
    _object("profiles/<uuid:pk>/upload/", "profile", control="action"),
    _object("profiles/<uuid:pk>/decide/", "profile", control="action"),
    _object("resumes/<uuid:pk>/xray/", "resume"),
    _collection("projects/"),
    _object("projects/<uuid:pk>/", "project"),
    _object("projects/<uuid:pk>/edit/", "project"),
    _object("projects/<uuid:pk>/skills/", "project", control="action"),
    _object("projects/<uuid:pk>/skills/<int:item_id>/", "rubric_skill", control="action"),
    _object("projects/<uuid:pk>/skills/<int:item_id>/remove/", "rubric_skill", control="action"),
    _object("projects/<uuid:pk>/approve/", "project", control="action"),
    _object("projects/<uuid:pk>/revise/", "project", control="action"),
    _object("projects/<uuid:pk>/close/", "project", control="action"),
    _object("projects/<uuid:pk>/run/", "project", control="action"),
    _object("runs/<uuid:pk>/", "run"),
    _object("results/<uuid:pk>/", "result"),
    _collection("bench/", has_marker=False),
    _collection("dashboard/"),
    _collection("utilisation/", has_marker=False),
    _collection("imports/"),
    _collection("imports/queue/"),
    _object("imports/queue/<uuid:pk>/", "queue_row", control="action"),
    _object("imports/<uuid:pk>/", "batch", has_marker=False),
    _object("imports/<uuid:pk>/mapping/", "batch", control="action"),
    _object("imports/<uuid:pk>/confirm/", "batch", control="action"),
    _object("imports/<uuid:pk>/rollback/", "batch", control="action"),
]

_ENTRIES = [
    *_TENANT_ROUTES,
    _public("login/", "The sign-in form. A visitor sees only the form."),
    _public("join/", "The invitation form. It reads nothing until a valid token is posted."),
    _control("logout/", "Ends the session. Serves no rows."),
    _control("", "Redirects to the role home page. Serves no rows."),
    _public("healthz/", "Liveness probe. Returns a fixed status body and reads no tenant data."),
    _public(
        "api/schema/",
        "OpenAPI schema. Describes the API surface and holds no records. Anonymous today, which "
        "AC-AUTH-07 forbids for API routes as written: reported to the lead for a decision.",
    ),
    _public(
        "api/docs/",
        "Swagger UI shell that loads api/schema/. Holds no records. Same AC-AUTH-07 conflict.",
    ),
    _public("admin/login/", "The admin sign-in form. An anonymous visitor sees only the form."),
    _operator("admin/", "Admin index. Lists model names only."),
    _operator("admin/logout/", "Ends the operator's session. Serves no records."),
    _operator("admin/password_change/", "The operator's own password form."),
    _operator("admin/password_change/done/", "Confirmation page. Serves no records."),
    _operator("admin/autocomplete/", "Lookup over admin-registered models, for all organisations."),
    _operator("admin/jsi18n/", "Translation catalogue for admin scripts. Serves no records."),
    _operator(
        "admin/r/<path:content_type_id>/<path:object_id>/",
        "View-on-site redirect. Takes an ID for any model, across all organisations.",
    ),
    _operator(
        "admin/(?P<app_label>auth|django_q|accounts)/$", "Per-app model list. Lists names only."
    ),
    _operator("admin/(?P<url>.*)$", "Admin catch-all. Serves no records."),
    *_admin_model("auth/group", "Permission groups. Global, and hold no tenant records."),
    *_admin_model("accounts/user", _USER_REASON),
    _operator("admin/accounts/user/<id>/password/", _USER_REASON),
    *_admin_model("django_q/schedule", _JOB_REASON),
    *_admin_model("django_q/success", _JOB_REASON),
    *_admin_model("django_q/failure", _JOB_REASON),
    *_admin_model("django_q/ormq", _JOB_REASON),
]

ROUTE_REGISTRY = {entry.route: entry for entry in _ENTRIES}
