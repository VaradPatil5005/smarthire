"""Factories for the auth user model."""

import factory
from django.conf import settings
from factory.django import Password

from tests.factories.base import BaseFactory

SYNTHETIC_EMAIL_DOMAIN = "example.test"
TEST_USER_PASSWORD = "synthetic-test-password"


class UserFactory(BaseFactory):
    """An active, unprivileged account. Pass is_staff or is_superuser to raise it."""

    class Meta:
        model = settings.AUTH_USER_MODEL

    username = factory.Sequence(lambda n: f"synthetic-user-{n}")
    email = factory.LazyAttribute(lambda user: f"{user.username}@{SYNTHETIC_EMAIL_DOMAIN}")
    password = Password(TEST_USER_PASSWORD)
