"""Walks Django's real URL resolver and compares what it finds with the registry."""

import re

from django.conf import settings
from django.urls import Resolver404, get_resolver, resolve
from django.urls.resolvers import URLResolver

from tests.isolation.registry import (
    ADMIN_CLASS_BY_MODEL,
    ADMIN_MODEL_ALLOW_LIST,
    OPERATOR_VIEWS_WITHOUT_ADMIN_ATTRIBUTES,
    PINNED_PUBLIC_ROUTES,
    RouteClass,
)

_CONVERTER = re.compile(r"<[^>]+>")
_GROUP = re.compile(r"\((?:\?P<\w+>)?([^()]*)\)")
_PLAIN_ALTERNATIVES = re.compile(r"[\w|-]+")
_SAMPLE_VALUE = "1"
_UUID_CONVERTER = re.compile(r"<uuid:[^>]+>")
_SAMPLE_UUID = "00000000-0000-4000-8000-000000000001"


def normalise_route(route):
    """Drop the top-level ^: resolve() keeps it on a top-level re_path, the walker does not."""
    return route.removeprefix("^")


def resolved_route(path):
    """The route Django itself reports for a URL path, comparable with discover_routes()."""
    return normalise_route(resolve(path).route)


def _walk(patterns, prefix=""):
    for pattern in patterns:
        # Joined as Django joins ResolverMatch.route, so a route here equals resolved_route(path).
        route = prefix + normalise_route(str(pattern.pattern))
        if isinstance(pattern, URLResolver):
            yield from _walk(pattern.url_patterns, route)
        else:
            yield route


def discover_routes():
    """Every route the active URLconf serves, including everything behind include()."""
    return set(_walk(get_resolver(settings.ROOT_URLCONF).url_patterns))


def assert_registry_complete(discovered, registry):
    """Fail on a route with no entry, and on an entry whose route no longer exists."""
    registered = {normalise_route(route) for route in registry}
    unregistered = sorted(discovered - registered)
    stale = sorted(registered - discovered)
    problems = []
    if unregistered:
        problems.append(f"Unregistered routes, classify in registry.py: {unregistered}")
    if stale:
        problems.append(f"Stale registry entries, the route is gone: {stale}")
    assert not problems, "\n".join(problems)


def assert_admin_registry_allowed(admin_registry):
    """D-008: exactly the allowed models, each with its pinned admin class and no inlines."""
    registered = {model._meta.label: model_admin for model, model_admin in admin_registry.items()}
    unexpected = sorted(set(registered) - ADMIN_MODEL_ALLOW_LIST)
    missing = sorted(ADMIN_MODEL_ALLOW_LIST - set(registered))
    assert not unexpected, (
        f"Models outside the D-008 admin allow-list: {unexpected}. Tenant-owned models stay out "
        "of admin; an exception needs a DECISION entry and an organisation-scoped get_queryset."
    )
    assert not missing, f"Allow-listed models no longer in admin, update the list: {missing}"
    for label, model_admin in registered.items():
        actual = view_identity(type(model_admin))
        assert actual == ADMIN_CLASS_BY_MODEL[label], (
            f"{label} is served by {actual}, not its pinned admin class. D-008 needs a DECISION."
        )
        inlines = [inline.__name__ for inline in model_admin.get_inlines(None, None)]
        assert not inlines, (
            f"{label} has inlines {inlines}, which expose models outside the D-008 allow-list."
        )


def takes_parameter(route):
    """Path converters, or any capturing regex group, named or not. Unparseable counts as yes."""
    if _CONVERTER.search(route):
        return True
    try:
        return re.compile(route).groups > 0
    except re.error:
        return True


def find_classification_problems(registry):
    """Rules that stop a tenant route being labelled into a class no one checks for 404s."""
    problems = []
    for key, entry in registry.items():
        route = entry.route
        if key != route:
            problems.append(f"{key}: key does not match entry route {route}")
        if not entry.reason.strip():
            problems.append(f"{route}: no reason given")
        if entry.route_class is RouteClass.OPERATOR_ADMIN and not route.startswith("admin/"):
            problems.append(f"{route}: operator admin class used outside admin/")
        if entry.route_class is RouteClass.PUBLIC_NO_TENANT_DATA:
            if route not in PINNED_PUBLIC_ROUTES:
                problems.append(f"{route}: not in the pinned public set, classify it as tenant")
            if takes_parameter(route):
                problems.append(f"{route}: takes a parameter, so it cannot be public")
        if entry.route_class is RouteClass.TENANT_COLLECTION and takes_parameter(route):
            problems.append(f"{route}: takes a parameter, so it must be TENANT_OBJECT")
        if entry.route_class is RouteClass.TENANT_OBJECT:
            if not takes_parameter(route):
                problems.append(f"{route}: takes no object ID, so it must be TENANT_COLLECTION")
            elif not entry.object_kind:
                problems.append(f"{route}: TENANT_OBJECT needs an object_kind")
    return problems


def view_identity(view):
    """Dotted path of a view: the class for a class-based view, otherwise the function."""
    target = getattr(view, "view_class", view)
    return f"{target.__module__}.{target.__qualname__}"


def _resolved_view(route):
    try:
        return resolve(sample_path(route)).func
    except Resolver404:
        return None


def find_public_view_problems(registry):
    """A public route must be served by its pinned view, not just answer like one."""
    problems = []
    for entry in registry.values():
        if entry.route_class is not RouteClass.PUBLIC_NO_TENANT_DATA:
            continue
        view = _resolved_view(entry.route)
        actual = view_identity(view) if view else "nothing"
        pinned = PINNED_PUBLIC_ROUTES.get(entry.route)
        if not pinned or actual != pinned.view:
            problems.append(f"{entry.route}: served by {actual}, not its pinned view")
    return problems


def find_operator_view_problems(registry):
    """An operator route must be a real admin view, not a view that redirects like one."""
    problems = []
    for entry in registry.values():
        if entry.route_class is not RouteClass.OPERATOR_ADMIN:
            continue
        view = _resolved_view(entry.route)
        actual = view_identity(view) if view else "nothing"
        if entry.route in OPERATOR_VIEWS_WITHOUT_ADMIN_ATTRIBUTES:
            if actual != OPERATOR_VIEWS_WITHOUT_ADMIN_ATTRIBUTES[entry.route]:
                problems.append(f"{entry.route}: served by {actual}, not its pinned view")
        elif not (hasattr(view, "admin_site") or hasattr(view, "model_admin")):
            problems.append(f"{entry.route}: served by {actual}, which is not an admin view")
    return problems


def sample_path(route, value=_SAMPLE_VALUE):
    """A concrete URL path that reaches this route, with `value` in each parameter."""

    def fill_group(match):
        body = match.group(1)
        return body.split("|")[0] if _PLAIN_ALTERNATIVES.fullmatch(body) else value

    # Groups first: the converter pattern would also match the <name> inside (?P<name>...).
    path = _GROUP.sub(fill_group, normalise_route(route))
    path = _UUID_CONVERTER.sub(_SAMPLE_UUID, path)
    path = _CONVERTER.sub(value, path)
    return "/" + path.removesuffix("$")
