"""AC-AUTH-11: a route that is not in the isolation registry fails the build.

`test_every_route_is_registered` is the gate. The tests below it prove the gate can fail, against
a test-only URLconf, so config/urls.py is never touched.
"""

import pytest

from tests.isolation.registry import ROUTE_REGISTRY, RouteClass, RouteEntry
from tests.isolation.routes import (
    assert_registry_complete,
    discover_routes,
    find_classification_problems,
    normalise_route,
    resolved_route,
    sample_path,
    takes_parameter,
)
from tests.isolation.urlconf_with_dummy import DUMMY_ROUTE

DUMMY_URLCONF = "tests.isolation.urlconf_with_dummy"
IMPOSTORS = "tests.isolation.urlconf_impostors"
DUMMY_ENTRY = RouteEntry(
    DUMMY_ROUTE, RouteClass.TENANT_OBJECT, "Fictional object route.", object_kind="dummy"
)


def test_every_route_is_registered():
    assert_registry_complete(discover_routes(), ROUTE_REGISTRY)


def test_real_registry_obeys_the_classification_rules():
    assert find_classification_problems(ROUTE_REGISTRY) == []


@pytest.mark.parametrize(
    ("route", "expected_class"),
    [
        ("healthz/", RouteClass.PUBLIC_NO_TENANT_DATA),
        ("api/schema/", RouteClass.PUBLIC_NO_TENANT_DATA),
        ("api/docs/", RouteClass.PUBLIC_NO_TENANT_DATA),
        ("admin/login/", RouteClass.PUBLIC_NO_TENANT_DATA),
        ("admin/", RouteClass.OPERATOR_ADMIN),
        ("admin/accounts/user/", RouteClass.OPERATOR_ADMIN),
        ("admin/accounts/user/<id>/password/", RouteClass.OPERATOR_ADMIN),
        ("admin/django_q/success/<path:object_id>/change/", RouteClass.OPERATOR_ADMIN),
        ("admin/(?P<url>.*)$", RouteClass.OPERATOR_ADMIN),
    ],
)
def test_known_routes_carry_their_classification(route, expected_class):
    assert ROUTE_REGISTRY[route].route_class is expected_class


def test_discovery_walks_into_included_urlconfs():
    routes = discover_routes()

    assert "healthz/" in routes
    assert "admin/accounts/user/<path:object_id>/change/" in routes


@pytest.mark.urls(DUMMY_URLCONF)
def test_unregistered_dummy_route_fails_the_gate():
    """The plan's proof: the same call the gate makes raises, and names the dummy route."""
    with pytest.raises(AssertionError, match="Unregistered") as failure:
        assert_registry_complete(discover_routes(), ROUTE_REGISTRY)

    assert DUMMY_ROUTE in str(failure.value)


@pytest.mark.urls(DUMMY_URLCONF)
def test_dummy_route_is_the_only_unregistered_route():
    assert discover_routes() - set(ROUTE_REGISTRY) == {DUMMY_ROUTE}


@pytest.mark.urls(DUMMY_URLCONF)
def test_dummy_route_passes_the_gate_once_registered():
    registry = {**ROUTE_REGISTRY, DUMMY_ROUTE: DUMMY_ENTRY}

    assert_registry_complete(discover_routes(), registry)


def test_dummy_route_is_absent_from_the_real_urlconf():
    assert DUMMY_ROUTE not in discover_routes()
    assert DUMMY_ROUTE not in ROUTE_REGISTRY


def test_stale_registry_entry_fails_the_gate():
    registry = {**ROUTE_REGISTRY, DUMMY_ROUTE: DUMMY_ENTRY}

    with pytest.raises(AssertionError, match="Stale") as failure:
        assert_registry_complete(discover_routes(), registry)

    assert DUMMY_ROUTE in str(failure.value)


@pytest.mark.parametrize(
    ("entry", "complaint"),
    [
        pytest.param(
            RouteEntry("api/things/<int:pk>/", RouteClass.PUBLIC_NO_TENANT_DATA, "Says public."),
            "takes a parameter",
            id="object-route-disguised-as-public",
        ),
        pytest.param(
            RouteEntry("api/things/", RouteClass.PUBLIC_NO_TENANT_DATA, "Says public."),
            "not in the pinned public set",
            id="api-list-route-disguised-as-public",
        ),
        pytest.param(
            RouteEntry(r"api/things/(\d+)/$", RouteClass.PUBLIC_NO_TENANT_DATA, "Says public."),
            "takes a parameter",
            id="unnamed-regex-group-disguised-as-public",
        ),
        pytest.param(
            RouteEntry("api/things/(?P<pk>[^/.]+)/$", RouteClass.PUBLIC_NO_TENANT_DATA, "Public."),
            "takes a parameter",
            id="regex-object-route-disguised-as-public",
        ),
        pytest.param(
            RouteEntry("api/things/", RouteClass.OPERATOR_ADMIN, "Says admin."),
            "outside admin/",
            id="api-route-disguised-as-admin",
        ),
        pytest.param(
            RouteEntry("healthz/", RouteClass.PUBLIC_NO_TENANT_DATA, "  "),
            "no reason",
            id="blank-reason",
        ),
        pytest.param(
            RouteEntry("api/things/<int:pk>/", RouteClass.TENANT_OBJECT, "No kind."),
            "object_kind",
            id="tenant-object-without-object-kind",
        ),
        pytest.param(
            RouteEntry("api/things/", RouteClass.TENANT_OBJECT, "No id.", object_kind="thing"),
            "takes no object ID",
            id="tenant-object-without-parameter",
        ),
        pytest.param(
            RouteEntry("api/things/<int:pk>/", RouteClass.TENANT_COLLECTION, "Has an id."),
            "takes a parameter",
            id="tenant-collection-with-parameter",
        ),
    ],
)
def test_misclassified_entries_are_reported(entry, complaint):
    problems = find_classification_problems({entry.route: entry})

    assert any(entry.route in problem and complaint in problem for problem in problems)


def test_correct_tenant_entries_are_not_reported():
    entries = [
        RouteEntry("api/things/<int:pk>/", RouteClass.TENANT_OBJECT, "Detail.", "thing"),
        RouteEntry("api/things/", RouteClass.TENANT_COLLECTION, "List."),
    ]

    assert find_classification_problems({e.route: e for e in entries}) == []


def test_registry_key_must_match_its_entry():
    entry = RouteEntry("healthz/", RouteClass.PUBLIC_NO_TENANT_DATA, "Reason.")

    problems = find_classification_problems({"other/": entry})

    assert len(problems) == 1
    assert "does not match" in problems[0]


@pytest.mark.parametrize(
    ("route", "expected"),
    [
        ("api/things/", False),
        ("api/things/<int:pk>/", True),
        ("admin/accounts/user/<id>/password/", True),
        ("api/things/(?P<pk>[^/.]+)/$", True),
        (r"api/things/(\d+)/$", True),
        (r"api/things/(?:new|old)/$", False),
        ("api/unbalanced(/", True),
    ],
)
def test_takes_parameter(route, expected):
    assert takes_parameter(route) is expected


def test_sample_path_fills_an_unnamed_group():
    assert sample_path(r"regex-unnamed/(\d+)/$") == "/regex-unnamed/1/"


@pytest.mark.urls(IMPOSTORS)
def test_top_level_regex_route_is_the_same_string_on_both_sides():
    """Django reports ^regex-top/$ from resolve(). A registry key may be written either way."""
    assert "regex-top/$" in discover_routes()
    assert normalise_route("^regex-top/$") == "regex-top/$"
    assert resolved_route("/regex-top/") == "regex-top/$"
    assert resolved_route(sample_path("^regex-top/$")) == "regex-top/$"


@pytest.mark.urls(IMPOSTORS)
def test_gate_accepts_a_caret_on_a_registry_key():
    routes = discover_routes()
    registry = {
        route: RouteEntry(route, RouteClass.OPERATOR_ADMIN, "Reason.")
        for route in routes - {"regex-top/$"}
    }
    registry["^regex-top/$"] = RouteEntry("^regex-top/$", RouteClass.TENANT_COLLECTION, "List.")

    assert_registry_complete(routes, registry)
