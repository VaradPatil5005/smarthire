"""A registry label is a claim. These tests check each claim against the running app."""

import re

import pytest
from django.contrib.auth import SESSION_KEY, get_user_model

from tests.factories import UserFactory
from tests.isolation.conftest import SENTINEL_MARKER
from tests.isolation.registry import (
    PINNED_PUBLIC_ROUTES,
    ROUTE_REGISTRY,
    RouteClass,
    RouteEntry,
)
from tests.isolation.routes import (
    find_operator_view_problems,
    find_public_view_problems,
    resolved_route,
    sample_path,
)

IMPOSTORS = "tests.isolation.urlconf_impostors"
LOGIN_PATH = "/admin/login/"
ANONYMOUS_LOGOUT_TARGET = {"admin/logout/": "/admin/"}
_ADMIN_MODEL = re.compile(r"^admin/(\w+/\w+)/")


def _routes_of(route_class):
    return sorted(e.route for e in ROUTE_REGISTRY.values() if e.route_class is route_class)


PUBLIC_ROUTES = _routes_of(RouteClass.PUBLIC_NO_TENANT_DATA)
OPERATOR_ROUTES = _routes_of(RouteClass.OPERATOR_ADMIN)


def _assert_no_sentinel(response):
    assert SENTINEL_MARKER not in response.content.decode(errors="replace")


def _seeded_path(route, seeded_admin_rows):
    """The route's URL, pointing at a row that really exists when the route has a model."""
    match = _ADMIN_MODEL.match(route)
    row = seeded_admin_rows.get(match.group(1)) if match else None
    return sample_path(route, value=str(row.pk)) if row else sample_path(route)


def _assert_turned_away(response, route):
    assert response.status_code == 302
    target = response["Location"].split("?")[0]
    assert target == ANONYMOUS_LOGOUT_TARGET.get(route, LOGIN_PATH)


@pytest.mark.parametrize("route", sorted(ROUTE_REGISTRY))
def test_sample_path_resolves_to_the_route_it_was_built_from(route):
    """Without this, a sloppy sample could fall into admin's catch-all and test the wrong view."""
    assert resolved_route(sample_path(route)) == route


def test_public_set_is_exactly_these_routes():
    assert set(PUBLIC_ROUTES) == {
        "healthz/",
        "api/schema/",
        "api/docs/",
        "admin/login/",
        "login/",
        "join/",
    }
    assert set(PINNED_PUBLIC_ROUTES) == set(PUBLIC_ROUTES)


def test_public_routes_are_served_by_their_pinned_views():
    assert find_public_view_problems(ROUTE_REGISTRY) == []


@pytest.mark.urls(IMPOSTORS)
def test_impostor_view_on_a_pinned_public_route_is_reported():
    entry = RouteEntry("healthz/", RouteClass.PUBLIC_NO_TENANT_DATA, "Claims to be the probe.")

    problems = find_public_view_problems({entry.route: entry})

    assert len(problems) == 1
    assert "impostor_of_healthz" in problems[0]


@pytest.mark.parametrize("route", PUBLIC_ROUTES)
def test_public_route_answers_anonymously_without_account_data(route, client, seeded_admin_rows):
    response = client.get(sample_path(route))

    assert response.status_code == 200
    _assert_no_sentinel(response)


@pytest.mark.parametrize("route", PUBLIC_ROUTES)
def test_public_route_shows_a_signed_in_user_no_other_account(route, client, seeded_admin_rows):
    client.force_login(UserFactory())

    response = client.get(sample_path(route))

    assert response.status_code == 200
    _assert_no_sentinel(response)


# admin/login/ greets a signed-in non-staff user by their own username, which is Django's own text.
@pytest.mark.parametrize("route", sorted(set(PUBLIC_ROUTES) - {"admin/login/"}))
def test_public_route_serves_no_data_about_the_signed_in_user(route, client, seeded_admin_rows):
    client.force_login(seeded_admin_rows["accounts/user"])

    response = client.get(sample_path(route))

    assert response.status_code == 200
    _assert_no_sentinel(response)


@pytest.mark.parametrize("signed_in", [False, True], ids=["anonymous", "signed-in"])
@pytest.mark.parametrize("route", PUBLIC_ROUTES)
def test_public_route_writes_nothing_on_post(route, signed_in, client, seeded_admin_rows):
    if signed_in:
        client.force_login(UserFactory())
    users_before = get_user_model().objects.count()
    session_user_before = client.session.get(SESSION_KEY)

    response = client.post(sample_path(route), {"username": "no-such-account", "password": "x"})

    assert response.status_code == PINNED_PUBLIC_ROUTES[route].post_status
    assert get_user_model().objects.count() == users_before
    assert client.session.get(SESSION_KEY) == session_user_before
    _assert_no_sentinel(response)


def test_operator_routes_are_served_by_admin_views():
    assert find_operator_view_problems(ROUTE_REGISTRY) == []


@pytest.mark.urls(IMPOSTORS)
def test_non_admin_view_under_admin_prefix_is_reported():
    """It redirects to the login page exactly as admin does, so only the view check catches it."""
    entry = RouteEntry("admin/not-really-admin/", RouteClass.OPERATOR_ADMIN, "Claims admin.")

    problems = find_operator_view_problems({entry.route: entry})

    assert len(problems) == 1
    assert "plain_view_redirecting_to_login" in problems[0]


@pytest.mark.parametrize("route", OPERATOR_ROUTES)
def test_operator_route_turns_away_anonymous_users(route, client, seeded_admin_rows):
    response = client.get(_seeded_path(route, seeded_admin_rows))

    _assert_turned_away(response, route)
    _assert_no_sentinel(response)


@pytest.mark.parametrize("route", OPERATOR_ROUTES)
def test_operator_route_turns_away_signed_in_non_staff(route, client, seeded_admin_rows):
    client.force_login(UserFactory())

    response = client.get(_seeded_path(route, seeded_admin_rows))

    _assert_turned_away(response, route)
    _assert_no_sentinel(response)


@pytest.mark.parametrize(
    "model_path",
    [
        "accounts/user",
        "auth/group",
        "django_q/schedule",
        "django_q/success",
        "django_q/failure",
        "django_q/ormq",
    ],
)
def test_seeded_rows_are_real_and_global_to_staff(model_path, client, seeded_admin_rows):
    """Control for the turn-away tests, and why the label is global and not a tenant class."""
    client.force_login(UserFactory(is_staff=True, is_superuser=True))

    response = client.get(sample_path(f"admin/{model_path}/"))

    assert response.status_code == 200
    assert SENTINEL_MARKER in response.content.decode()


def test_tests_in_this_package_are_auto_marked_isolation(request):
    assert request.node.get_closest_marker("isolation") is not None
