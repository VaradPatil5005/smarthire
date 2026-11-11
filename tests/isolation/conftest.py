"""Fixtures for the isolation suite."""

from uuid import uuid4

import pytest
from django.contrib.auth.models import Group
from django.utils import timezone
from django_q.models import OrmQ, Schedule, Task
from django_q.signing import SignedPackage

from tests.factories import UserFactory

SENTINEL_MARKER = "isolation-sentinel"
SENTINEL_USERNAME = f"{SENTINEL_MARKER}-user"
SENTINEL_EMAIL = f"{SENTINEL_MARKER}@example.test"
SEEDED_JOB_FUNC = "math.floor"


@pytest.fixture
def sentinel_user(db):
    """An ordinary account whose identity must never appear in a response it should not."""
    return UserFactory(username=SENTINEL_USERNAME, email=SENTINEL_EMAIL)


def _seed_task(success):
    now = timezone.now()
    return Task.objects.create(
        id=uuid4().hex,
        name=f"{SENTINEL_MARKER}-task",
        func=SEEDED_JOB_FUNC,
        started=now,
        stopped=now,
        success=success,
    )


def _seed_queue_row():
    payload = SignedPackage.dumps(
        {"id": uuid4().hex, "name": f"{SENTINEL_MARKER}-queued", "func": SEEDED_JOB_FUNC}
    )
    return OrmQ.objects.create(key="isolation", payload=payload)


@pytest.fixture
def seeded_admin_rows(sentinel_user):
    """One marked row per admin-registered model, keyed by its admin path, so routes have data."""
    return {
        "accounts/user": sentinel_user,
        "auth/group": Group.objects.create(name=f"{SENTINEL_MARKER}-group"),
        "django_q/schedule": Schedule.objects.create(
            name=f"{SENTINEL_MARKER}-schedule", func=SEEDED_JOB_FUNC
        ),
        "django_q/success": _seed_task(success=True),
        "django_q/failure": _seed_task(success=False),
        "django_q/ormq": _seed_queue_row(),
    }
