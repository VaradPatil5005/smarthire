"""Organisations, memberships and the organisation-scoped query path."""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Organisation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    security_policy = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return self.name


class Role(models.TextChoices):
    CANDIDATE = "CANDIDATE", "Candidate"
    RECRUITER = "RECRUITER", "Recruiter"
    DELIVERY_MANAGER = "DELIVERY_MANAGER", "Delivery manager"
    ADMIN = "ADMIN", "Admin"


STAFF_ROLES = frozenset({Role.RECRUITER, Role.DELIVERY_MANAGER, Role.ADMIN})
RUBRIC_APPROVER_ROLES = frozenset({Role.DELIVERY_MANAGER, Role.ADMIN})
IMPORT_ROLES = frozenset({Role.ADMIN})


class MembershipQuerySet(models.QuerySet):
    def active(self):
        return self.filter(revoked_at__isnull=True)


class Membership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=Role.choices)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    objects = MembershipQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organisation"], name="unique_membership_per_organisation"
            )
        ]

    def __str__(self) -> str:
        return f"membership {self.pk}"

    @property
    def is_staff_role(self) -> bool:
        return self.role in STAFF_ROLES

    @classmethod
    def current_for(cls, user):
        """The oldest active membership. Never read from request data."""
        return (
            cls.objects.active()
            .filter(user=user)
            .select_related("organisation")
            .order_by("created_at", "pk")
            .first()
        )


class TenantQuerySet(models.QuerySet):
    def for_org(self, organisation):
        return self.filter(organisation=organisation)


class TenantModel(models.Model):
    """Base for every row that belongs to one organisation."""

    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="+")

    objects = TenantQuerySet.as_manager()

    class Meta:
        abstract = True


class Invitation(TenantModel):
    """A single-use, expiring way into one organisation. The raw token is never stored."""

    token_hash = models.CharField(max_length=64, unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CANDIDATE)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return f"invitation {self.pk}"
