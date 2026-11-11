"""The cross-tenant harness: every tenant route, every method, against a second organisation.

Object routes need the owner's positive control, then the other organisation's 404, then the same
status and body as an ID that has never existed, so a response cannot reveal that an object exists.
Collection routes must return only the caller's rows. See tests/isolation/world.py.
"""

import re

import pytest
from django.apps import apps

from tests.isolation.registry import ROUTE_REGISTRY, RouteClass

_TENANT_CLASSES = {RouteClass.TENANT_OBJECT, RouteClass.TENANT_COLLECTION}
_ORGANISATION_NAMES = {"organisation", "organization"}
_PROBED_METHODS = ("get", "head", "post", "put", "patch", "delete")
_METHODS_WITH_BODY = {"post", "put", "patch"}
_NO_TENANT_ROUTES = (
    "0 tenant routes registered, so nothing has been checked yet. "
    "The first registered tenant route removes this skip and runs the case."
)


_CSRF = re.compile(r'name="csrfmiddlewaretoken" value="[^"]*"')


def _body(response):
    if response.streaming:
        return b"".join(response.streaming_content).decode(errors="replace")
    return response.content.decode(errors="replace")


def _comparable(response):
    """Status and body, minus the per-request CSRF token. A real difference here is an oracle."""
    return response.status_code, _CSRF.sub("", _body(response))


def _fill(route, kwargs):
    return re.sub(r"<(?:\w+:)?(\w+)>", lambda m: str(kwargs[m.group(1)]), "/" + route)


def assert_collection_scoped(route, path, client, own_marker, other_marker, has_marker):
    response = client.get(path)
    assert response.status_code in (200, 302, 405), f"{route}: GET returned {response.status_code}"
    body = _body(response)
    assert other_marker not in body, f"Cross-tenant breach on {route}: other organisation data"
    if has_marker and response.status_code == 200:
        assert own_marker in body, f"No positive control on {route}: own rows are missing"


def assert_no_oracle(route, path, missing_path, other_client, marker):
    """Another organisation's object must answer exactly like an ID that never existed."""
    for method in ("options", *_PROBED_METHODS):
        here = _send(other_client, method, path)
        absent = _send(other_client, method, missing_path)
        assert _comparable(here) == _comparable(absent), (
            f"Cross-tenant oracle on {route}: {method.upper()} differs from a missing ID"
        )
        if method != "options":
            assert here.status_code in (404, 405), (
                f"Cross-tenant breach on {route}: {method.upper()} returned {here.status_code}"
            )
        assert marker not in _body(here), f"Cross-tenant leak on {route}: {method.upper()}"


def assert_action_denied(route, path, missing_path, owner_client, other_client, marker):
    """A POST-only route: denied like a missing ID for the other side, reachable for the owner."""
    assert_no_oracle(route, path, missing_path, other_client, marker)
    allowed = _allowed_methods(owner_client, path)
    method = next(m for m in ("post", "patch", "delete") if m in allowed)
    control = _send(owner_client, method, path)
    assert control.status_code not in (404, 405), (
        f"No positive control on {route}: owner got {control.status_code}"
    )


def run_cross_tenant_case(entry):
    from tests.isolation.world import A_MARKER, B_MARKER, build_world, kwargs_for, missing_kwargs

    tenant_a, tenant_b = build_world()
    other_client = tenant_a.client(entry.actor)
    owner_client = tenant_b.client(entry.actor)
    if entry.route_class is RouteClass.TENANT_COLLECTION:
        path = "/" + entry.route
        assert_collection_scoped(
            entry.route, path, other_client, A_MARKER, B_MARKER, entry.has_marker
        )
        return
    kwargs = kwargs_for(entry.object_kind, tenant_b)
    path = _fill(entry.route, kwargs)
    missing_path = _fill(entry.route, missing_kwargs(kwargs))
    if entry.control == "action":
        assert_action_denied(entry.route, path, missing_path, owner_client, other_client, B_MARKER)
        return
    if entry.control == "binary":
        assert owner_client.get(path).status_code == 200
    elif entry.has_marker:
        assert_cross_tenant_denied(
            entry.route,
            path,
            owner_client=owner_client,
            other_client=other_client,
            forbidden_markers=[B_MARKER],
        )
    else:
        assert owner_client.get(path).status_code == 200
    assert_no_oracle(entry.route, path, missing_path, other_client, B_MARKER)


def _send(client, method, path):
    if method in _METHODS_WITH_BODY:
        return getattr(client, method)(path, data="{}", content_type="application/json")
    return getattr(client, method)(path)


def _allowed_methods(owner_client, path):
    """What the route declares. No Allow header fails closed: every method must then be 404."""
    allow = owner_client.options(path).headers.get("Allow")
    if allow is None:
        return set(_PROBED_METHODS)
    return {method.strip().lower() for method in allow.split(",")}


def assert_cross_tenant_denied(route, path, *, owner_client, other_client, forbidden_markers):
    """The owner reads the object, then the other organisation gets 404 on every allowed method.

    The owner's 200 is the positive control: without it an always-404 route would look isolated.
    The markers must appear for the owner, or checking the other organisation's body proves nothing.
    A method the route does not declare may answer 405, which reaches no object. 403 is a breach
    because it confirms the object exists.
    """
    markers = list(forbidden_markers)
    if not markers or not all(markers):
        raise ValueError("forbidden_markers needs at least one non-empty marker")

    control = owner_client.get(path)
    assert control.status_code == 200, (
        f"No positive control on {route}: owner got {control.status_code}, expected 200"
    )
    assert any(marker in _body(control) for marker in markers), (
        f"No positive control on {route}: owner's response contains none of {markers}"
    )

    allowed = _allowed_methods(owner_client, path)
    responses = [("options", other_client.options(path))]
    for method in _PROBED_METHODS:
        response = _send(other_client, method, path)
        permitted = {404} if method in allowed else {404, 405}
        assert response.status_code in permitted, (
            f"Cross-tenant breach on {route}: {method.upper()} returned "
            f"{response.status_code}, expected one of {sorted(permitted)}"
        )
        responses.append((method, response))

    for method, response in responses:
        leaked = [marker for marker in markers if marker in _body(response)]
        assert not leaked, f"Cross-tenant breach on {route}: {method.upper()} body has {leaked}"


def tenant_owned_models(models=None):
    """Models with a foreign key or one-to-one to an organisation, by field or target name."""
    candidates = apps.get_models() if models is None else models
    return [model for model in candidates if _has_organisation_key(model)]


def _has_organisation_key(model):
    for field in model._meta.get_fields():
        if not (field.many_to_one or field.one_to_one) or not field.concrete:
            continue
        if field.name in _ORGANISATION_NAMES:
            return True
        if field.related_model._meta.model_name in _ORGANISATION_NAMES:
            return True
    return False


def cross_tenant_cases(registry=ROUTE_REGISTRY, models=None):
    """One case per tenant route. With none, a visible skip naming any tenant models (D-009)."""
    routes = sorted(
        (e for e in registry.values() if e.route_class in _TENANT_CLASSES),
        key=lambda e: e.route,
    )
    if routes:
        return [pytest.param(entry, id=entry.route) for entry in routes]
    owned = [model._meta.label for model in tenant_owned_models(models)]
    reason = f"{_NO_TENANT_ROUTES} Tenant models waiting for routes: {owned or 'none'}."
    return [pytest.param(None, id="no-tenant-routes-yet", marks=pytest.mark.skip(reason=reason))]
