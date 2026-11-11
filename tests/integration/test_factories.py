"""Smoke tests for tests/factories: only models that exist today (the auth User)."""

import pytest
from django.contrib.auth import get_user_model
from factory.errors import FactoryError

from tests.factories import BaseFactory, UserFactory
from tests.factories.users import SYNTHETIC_EMAIL_DOMAIN, TEST_USER_PASSWORD


@pytest.mark.django_db
def test_user_factory_persists_a_usable_active_user(client):
    user = UserFactory()

    assert get_user_model().objects.filter(pk=user.pk).exists()
    assert user.is_active
    assert not user.is_staff
    assert not user.is_superuser
    assert client.login(username=user.username, password=TEST_USER_PASSWORD)


@pytest.mark.django_db
def test_user_factory_stores_a_hash_not_the_plain_password():
    user = UserFactory()

    assert user.password != TEST_USER_PASSWORD
    assert user.check_password(TEST_USER_PASSWORD)


@pytest.mark.django_db
def test_user_factory_generates_distinct_synthetic_identities():
    users = UserFactory.create_batch(3)

    assert len({u.username for u in users}) == 3
    assert len({u.email for u in users}) == 3
    assert all(u.email.endswith(f"@{SYNTHETIC_EMAIL_DOMAIN}") for u in users)


def test_user_factory_build_touches_no_database():
    # No django_db mark: pytest-django raises if this reaches the database.
    assert UserFactory.build().pk is None


def test_base_factory_is_abstract():
    with pytest.raises(FactoryError):
        BaseFactory()
