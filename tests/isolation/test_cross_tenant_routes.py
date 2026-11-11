"""AC-AUTH-09, AC-AUTH-10: another organisation's objects return 404 on every tenant route.

The harness's own check is also proved here through real HTTP requests against test-only views, so
a route that always answers 404 cannot look isolated.
"""

import pytest
from django.db import models
from django.test import Client
from django.test.utils import isolate_apps

from tests.factories import UserFactory
from tests.isolation.harness import (
    assert_cross_tenant_denied,
    cross_tenant_cases,
    run_cross_tenant_case,
    tenant_owned_models,
)
from tests.isolation.registry import RouteClass, RouteEntry
from tests.isolation.urlconf_probes import ORG_B_MARKER, OWNER_USERNAME

PROBES = "tests.isolation.urlconf_probes"
TENANT_OBJECT = RouteEntry("api/things/<int:pk>/", RouteClass.TENANT_OBJECT, "Detail.", "thing")
TENANT_COLLECTION = RouteEntry("api/things/", RouteClass.TENANT_COLLECTION, "List.")
PUBLIC = RouteEntry("healthz/", RouteClass.PUBLIC_NO_TENANT_DATA, "Probe.")


@pytest.mark.django_db
@pytest.mark.parametrize("entry", cross_tenant_cases())
def test_other_organisations_objects_return_404(entry):
    run_cross_tenant_case(entry)


def test_no_tenant_routes_or_models_means_a_skip_and_not_a_pass():
    case = cross_tenant_cases({PUBLIC.route: PUBLIC}, models=[])[0]

    assert [mark.name for mark in case.marks] == ["skip"]
    assert "0 tenant routes" in case.marks[0].kwargs["reason"]


def test_a_registered_tenant_route_removes_the_skip():
    registry = {e.route: e for e in (PUBLIC, TENANT_OBJECT, TENANT_COLLECTION)}

    cases = cross_tenant_cases(registry, models=[])

    assert [case.values[0] for case in cases] == [TENANT_COLLECTION, TENANT_OBJECT]
    assert all(not case.marks for case in cases)


def _probe_model(name, **fields):
    meta = type("Meta", (), {"app_label": "core"})
    return type(name, (models.Model,), {"__module__": __name__, "Meta": meta, **fields})


@isolate_apps("apps.core")
def test_only_models_with_an_organisation_key_count_as_tenant_owned():
    organisation = _probe_model("Organisation")
    thing = _probe_model(
        "Thing", organisation=models.ForeignKey(organisation, on_delete=models.CASCADE)
    )
    link = _probe_model("Link", owner=models.OneToOneField(organisation, on_delete=models.CASCADE))
    bystander = _probe_model("Bystander")

    assert tenant_owned_models([organisation, thing, link, bystander]) == [thing, link]


@isolate_apps("apps.core")
def test_tenant_models_with_no_tenant_route_skip_and_name_the_models():
    """D-009: failing here would deadlock T1.3, T2.1 and T2.2 under the task hook."""
    organisation = _probe_model("Organisation")
    thing = _probe_model(
        "Thing", organisation=models.ForeignKey(organisation, on_delete=models.CASCADE)
    )

    case = cross_tenant_cases({PUBLIC.route: PUBLIC}, models=[thing])[0]

    assert [mark.name for mark in case.marks] == ["skip"]
    assert "core.Thing" in case.marks[0].kwargs["reason"]


def test_at_least_one_tenant_route_is_registered():
    """The D-009 skip cannot outlive T2.2."""
    assert len(cross_tenant_cases()) > 1


def _signed_in(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def owner_client(db):
    return _signed_in(UserFactory(username=OWNER_USERNAME))


@pytest.fixture
def other_client(db):
    return _signed_in(UserFactory())


def _check(path, owner_client, other_client, markers=(ORG_B_MARKER,)):
    assert_cross_tenant_denied(
        path,
        path,
        owner_client=owner_client,
        other_client=other_client,
        forbidden_markers=markers,
    )


@pytest.mark.urls(PROBES)
@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/probe/leaks-data/", id="200-with-data"),
        pytest.param("/probe/forbidden/", id="403-reveals-the-object-exists"),
        pytest.param("/probe/redirects/", id="302"),
        pytest.param("/probe/server-error/", id="500"),
        pytest.param("/probe/not-found-but-leaks/", id="404-whose-body-leaks"),
        pytest.param("/probe/post-leaks/", id="safe-get-but-post-leaks"),
        pytest.param("/probe/options-leaks/", id="options-body-leaks"),
        pytest.param("/probe/delete-forbidden/", id="allowed-delete-answers-403"),
        pytest.param("/probe/bare-405/", id="405-without-allow-header-fails-closed"),
    ],
)
def test_check_catches_every_wrong_answer(path, owner_client, other_client):
    with pytest.raises(AssertionError, match="Cross-tenant breach"):
        _check(path, owner_client, other_client)


@pytest.mark.urls(PROBES)
@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/probe/always-404/", id="always-404-route"),
        pytest.param("/probe/owner-gets-403/", id="owner-is-refused"),
        pytest.param("/probe/owner-no-marker/", id="marker-never-shown-to-owner"),
    ],
)
def test_a_404_does_not_count_without_a_positive_control(path, owner_client, other_client):
    with pytest.raises(AssertionError, match="No positive control"):
        _check(path, owner_client, other_client)


@pytest.mark.urls(PROBES)
@pytest.mark.parametrize(
    "markers",
    [pytest.param((), id="empty"), pytest.param(("",), id="blank-marker-matches-any-body")],
)
def test_markers_are_required(markers, owner_client, other_client):
    with pytest.raises(ValueError, match="marker"):
        _check("/probe/correctly-hidden/", owner_client, other_client, markers=markers)


def test_markers_have_no_default():
    with pytest.raises(TypeError):
        assert_cross_tenant_denied("r", "/p/", owner_client=None, other_client=None)


@pytest.mark.urls(PROBES)
@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/probe/correctly-hidden/", id="404-on-every-method"),
        pytest.param("/probe/correctly-hidden-get-only/", id="405-on-undeclared-methods"),
    ],
)
def test_check_accepts_a_correctly_scoped_route(path, owner_client, other_client):
    _check(path, owner_client, other_client)
