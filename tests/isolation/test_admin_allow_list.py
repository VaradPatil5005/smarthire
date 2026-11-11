"""D-008: the models registered in admin are pinned, so no tenant model gets there unnoticed."""

import pytest
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.contenttypes.models import ContentType

from tests.isolation.registry import ADMIN_MODEL_ALLOW_LIST
from tests.isolation.routes import assert_admin_registry_allowed


class TenantRowInline(admin.TabularInline):
    """LogEntry stands in for a tenant model: it has a foreign key to the user."""

    model = LogEntry


class UserAdminWithInline(UserAdmin):
    inlines = [TenantRowInline]


def test_allow_list_is_exactly_what_d008_names():
    named_by_d008 = {
        "accounts.User",
        "auth.Group",
        "django_q.Schedule",
        "django_q.Success",
        "django_q.Failure",
        "django_q.OrmQ",
    }

    assert named_by_d008 == ADMIN_MODEL_ALLOW_LIST


def test_admin_registry_matches_the_allow_list():
    assert_admin_registry_allowed(admin.site._registry)


def test_registering_another_model_fails_the_check():
    """The repro: a real registration on the real admin site. ContentType stands in for it."""
    admin.site.register(ContentType)
    try:
        with pytest.raises(AssertionError, match="contenttypes.ContentType"):
            assert_admin_registry_allowed(admin.site._registry)
    finally:
        admin.site.unregister(ContentType)


def test_removing_an_allowed_model_also_fails_the_check():
    registered = {m: a for m, a in admin.site._registry.items() if m._meta.label != "auth.Group"}

    with pytest.raises(AssertionError, match="auth.Group"):
        assert_admin_registry_allowed(registered)


def test_inline_on_an_allowed_admin_class_fails_the_check():
    """The repro: a model not registered in admin, reachable through allow-listed auth.User."""
    user_model = get_user_model()
    registered = {**admin.site._registry, user_model: UserAdminWithInline(user_model, admin.site)}

    with pytest.raises(AssertionError, match="UserAdminWithInline"):
        assert_admin_registry_allowed(registered)


def test_inline_added_to_the_pinned_admin_instance_fails_the_check(monkeypatch):
    user_admin = admin.site._registry[get_user_model()]
    monkeypatch.setattr(user_admin, "inlines", [TenantRowInline])

    with pytest.raises(AssertionError, match="TenantRowInline"):
        assert_admin_registry_allowed(admin.site._registry)


def test_replacing_an_allowed_admin_class_fails_even_without_inlines():
    class QuietSubclass(UserAdmin):
        pass

    user_model = get_user_model()
    registered = {**admin.site._registry, user_model: QuietSubclass(user_model, admin.site)}

    with pytest.raises(AssertionError, match="QuietSubclass"):
        assert_admin_registry_allowed(registered)
