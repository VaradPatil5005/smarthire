import importlib
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import SESSION_KEY, authenticate, get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.services import create_invitation, redeem_invitation
from apps.matching.models import MatchRun
from apps.talent.models import TalentProfile
from apps.tenancy.models import Membership, Role
from tests.factories.world import client_for, make_org, make_profile, make_project, make_user

PASSWORD = "test-only-password-1"
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()


@pytest.mark.parametrize(
    ("role", "home"),
    [
        (Role.CANDIDATE, "/me/"),
        (Role.RECRUITER, "/projects/"),
        (Role.DELIVERY_MANAGER, "/bench/"),
        (Role.ADMIN, "/dashboard/"),
    ],
)
def test_each_role_logs_in_and_lands_on_its_home(role, home):
    """AC-AUTH-01"""
    user = make_user(make_org(), role)
    client = Client()
    response = client.post("/login/", {"username": user.username, "password": PASSWORD})
    assert response.status_code == 302
    assert SESSION_KEY in client.session
    assert client.get(response.url).url == home
    assert client.get(home).status_code == 200


def test_logout_ends_the_session_and_tenant_routes_return_nothing():
    """AC-AUTH-02"""
    org = make_org()
    user = make_user(org)
    make_profile(org, name="Marked person")
    client = client_for(user)
    assert b"Marked person" in client.get("/profiles/").content
    assert client.post("/logout/").status_code == 302
    page = client.get("/profiles/")
    api = client.get("/api/profiles/")
    assert b"Marked person" not in page.content
    assert api.status_code in (401, 403)
    assert b"Marked person" not in api.content


def test_wrong_password_creates_no_session():
    """AC-AUTH-03"""
    user = make_user(make_org())
    client = Client()
    client.post("/login/", {"username": user.username, "password": "wrong-password"})
    assert SESSION_KEY not in client.session


@override_settings(LOGIN_THROTTLE_MAX_FAILURES=5, LOGIN_THROTTLE_WINDOW_SECONDS=900)
def test_login_throttle_is_per_account_and_ip():
    """AC-AUTH-04"""
    user = make_user(make_org())
    attacker = Client(REMOTE_ADDR="10.0.0.1")
    for _ in range(5):
        attacker.post("/login/", {"username": user.username, "password": "wrong"})
    attacker.post("/login/", {"username": user.username, "password": PASSWORD})
    assert SESSION_KEY not in attacker.session
    other_ip = Client(REMOTE_ADDR="10.0.0.2")
    other_ip.post("/login/", {"username": user.username, "password": PASSWORD})
    assert SESSION_KEY in other_ip.session


@pytest.mark.parametrize("module", ["config.settings.base", "config.settings.prod"])
def test_argon2_is_first_and_md5_is_absent(module, monkeypatch):
    """AC-AUTH-05"""
    monkeypatch.setenv("DJANGO_SECRET_KEY", "test-only-not-a-secret")
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "example.test")
    settings_module = importlib.reload(importlib.import_module("config.settings.base"))
    if module.endswith("prod"):
        settings_module = importlib.reload(importlib.import_module(module))
    hashers = settings_module.PASSWORD_HASHERS
    assert hashers[0] == "django.contrib.auth.hashers.Argon2PasswordHasher"
    assert not any("MD5" in hasher for hasher in hashers)


def test_environment_file_loading_can_be_disabled_without_accessing_file(monkeypatch):
    from config.settings.base import _load_dotenv

    monkeypatch.setenv("DJANGO_LOAD_DOTENV", "0")
    path = Mock()
    _load_dotenv(path)
    path.exists.assert_not_called()
    path.read_text.assert_not_called()


def test_environment_file_loading_still_preserves_explicit_environment(monkeypatch):
    import os

    from config.settings.base import _load_dotenv

    monkeypatch.delenv("DJANGO_LOAD_DOTENV", raising=False)
    monkeypatch.setenv("SMARTHIRE_TEST_DOTENV", "explicit")
    path = Mock()
    path.exists.return_value = True
    path.read_text.return_value = "SMARTHIRE_TEST_DOTENV=file-value"
    _load_dotenv(path)
    assert os.environ["SMARTHIRE_TEST_DOTENV"] == "explicit"


def test_user_created_under_real_hashers_stores_argon2():
    """AC-AUTH-05"""
    with override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.Argon2PasswordHasher"]):
        user = get_user_model().objects.create_user("argon-user", password=PASSWORD)
    assert user.password.startswith("argon2")


def test_session_key_changes_on_login():
    """AC-AUTH-06"""
    user = make_user(make_org())
    client = Client()
    session = client.session
    session["visited"] = True
    session.save()
    before = client.session.session_key
    client.post("/login/", {"username": user.username, "password": PASSWORD})
    assert client.session.session_key != before


def test_organisation_in_request_data_is_ignored():
    """AC-AUTH-12"""
    org_a, org_b = make_org(), make_org()
    client = client_for(make_user(org_a))
    make_profile(org_b, name="Other organisation person")
    response = client.get(
        f"/api/profiles/?organisation={org_b.pk}", HTTP_X_ORGANISATION=str(org_b.pk)
    )
    assert b"Other organisation person" not in response.content
    created = client.post(
        "/api/profiles/",
        {"display_name": "New", "title": "T", "organisation": str(org_b.pk)},
        content_type="application/json",
    )
    assert created.status_code == 201
    assert TalentProfile.objects.get(pk=created.json()["id"]).organisation == org_a


def test_scoped_manager_returns_only_the_organisations_rows():
    """AC-AUTH-13"""
    org_a, org_b = make_org(), make_org()
    mine = make_profile(org_a)
    make_profile(org_b)
    assert list(TalentProfile.objects.for_org(org_a)) == [mine]


def test_cross_organisation_link_is_refused_by_the_model():
    """AC-AUTH-14"""
    org_a, org_b = make_org(), make_org()
    project = make_project(org_b)
    rubric = project.latest_rubric()
    run = MatchRun(
        organisation=org_a,
        project=project,
        rubric_version=rubric,
        dictionary_version_id=1,
        run_date=timezone.now().date(),
        idempotency_key="k",
        payload_hash="x",
    )
    with pytest.raises(Exception, match="share one organisation"):
        run.save()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/projects/{project}/rubrics/1/approve/"),
        ("post", "/api/projects/{project}/runs/"),
        ("post", "/api/results/{result}/reviews/"),
        ("get", "/api/resumes/{resume}/xray/"),
        ("get", "/api/runs/{run}/export.csv"),
    ],
)
def test_candidate_is_refused_with_403_and_nothing_is_written(method, path):
    """AC-AUTH-15, AC-DASH-17"""
    from apps.matching.services import create_run
    from tests.isolation.world import build_world

    tenant, _other = build_world()
    client = client_for(tenant.candidate)
    url = path.format(
        project=tenant.draft_project.pk,
        result=tenant.result.pk,
        resume=tenant.resume.pk,
        run=tenant.run.pk,
    )
    runs_before = MatchRun.objects.count()
    response = getattr(client, method)(url, content_type="application/json")
    assert response.status_code == 403
    assert MatchRun.objects.count() == runs_before
    assert create_run is not None


def test_second_membership_is_rejected_by_the_database():
    """AC-AUTH-17"""
    org = make_org()
    user = make_user(org)
    with pytest.raises(IntegrityError), transaction.atomic():
        Membership.objects.create(user=user, organisation=org, role=Role.ADMIN)


def test_revoked_user_with_old_session_gets_no_tenant_data():
    """AC-AUTH-18, AC-DASH-17"""
    org = make_org()
    user = make_user(org)
    make_profile(org, name="Marked person")
    client = client_for(user)
    assert client.get("/api/profiles/").status_code == 200
    Membership.objects.filter(user=user).update(revoked_at=timezone.now())
    response = client.get("/api/profiles/")
    assert response.status_code == 403
    assert client.get("/profiles/").status_code == 403


def test_form_post_without_csrf_is_refused():
    """AC-AUTH-19"""
    org = make_org()
    user = make_user(org)
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    before = TalentProfile.objects.count()
    response = client.post("/profiles/", {"display_name": "X", "title": "Y"})
    assert response.status_code == 403
    assert TalentProfile.objects.count() == before


def test_invitation_is_single_use_and_the_role_comes_from_it():
    """AC-IMPORT-19, AC-CAND-01"""
    org = make_org()
    _invitation, token = create_invitation(org, Role.CANDIDATE)
    data = {
        "token": token,
        "username": "joiner",
        "password1": "a-long-Unique-pass-77",
        "password2": "a-long-Unique-pass-77",
        "role": Role.ADMIN,
    }
    response = Client().post(reverse("join"), data)
    assert response.status_code == 302
    membership = Membership.objects.get(user__username="joiner")
    assert (membership.organisation, membership.role) == (org, Role.CANDIDATE)
    again = Client().post(reverse("join"), {**data, "username": "joiner2"})
    assert b"expired or was already used" in again.content
    assert not get_user_model().objects.filter(username="joiner2").exists()


def test_expired_invitation_is_refused():
    """AC-IMPORT-19"""
    _invitation, token = create_invitation(make_org(), Role.CANDIDATE, days=-1)
    response = Client().post(
        reverse("join"),
        {
            "token": token,
            "username": "late",
            "password1": "a-long-Unique-pass-77",
            "password2": "a-long-Unique-pass-77",
        },
    )
    assert b"expired" in response.content


def test_invitation_expiry_is_rechecked_when_redeemed():
    invitation, _token = create_invitation(make_org(), Role.CANDIDATE)
    user = get_user_model().objects.create_user("late-redeemer", password=PASSWORD)
    invitation.expires_at = timezone.now() - timedelta(seconds=1)
    invitation.save(update_fields=["expires_at"])

    with pytest.raises(ValueError, match="expired"):
        redeem_invitation(invitation, user)

    invitation.refresh_from_db()
    assert invitation.used_at is None
    assert not Membership.objects.filter(user=user).exists()


def test_invitation_conflict_rolls_back_new_account_and_shows_recovery():
    _invitation, token = create_invitation(make_org(), Role.CANDIDATE)
    with patch("apps.accounts.views.redeem_invitation", side_effect=ValueError("Invitation used")):
        response = Client().post(
            reverse("join"),
            {
                "token": token,
                "username": "conflicted-joiner",
                "password1": "a-long-Unique-pass-77",
                "password2": "a-long-Unique-pass-77",
            },
        )

    assert response.status_code == 200
    assert b"expired or was already used" in response.content
    assert not get_user_model().objects.filter(username="conflicted-joiner").exists()


def test_authenticate_uses_the_custom_user_model():
    """AC-AUTH-01: every role logs in through the same user model."""
    user = make_user(make_org())
    assert authenticate(username=user.username, password=PASSWORD) == user


def test_every_api_route_refuses_anonymous_access():
    """AC-AUTH-07"""
    from tests.isolation.registry import ROUTE_REGISTRY, RouteClass
    from tests.isolation.routes import sample_path

    checked = 0
    client = Client()
    for entry in ROUTE_REGISTRY.values():
        if not entry.route.startswith("api/"):
            continue
        if entry.route_class is RouteClass.PUBLIC_NO_TENANT_DATA:
            continue
        response = client.get(sample_path(entry.route))
        assert response.status_code in (401, 403), entry.route
        checked += 1
    assert checked >= 30
