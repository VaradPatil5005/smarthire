"""Shared API rules. Organisation always comes from the verified membership, never the request."""

from django.http import Http404
from rest_framework.permissions import BasePermission

from apps.tenancy.models import IMPORT_ROLES, RUBRIC_APPROVER_ROLES, STAFF_ROLES


class HasMembership(BasePermission):
    """Signed in with an active membership. A revoked user has none, so gets no tenant data."""

    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and getattr(request, "membership", None))


class _RolePermission(HasMembership):
    roles = frozenset()

    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.membership.role in self.roles


class IsStaffRole(_RolePermission):
    roles = STAFF_ROLES


class IsRubricApprover(_RolePermission):
    roles = RUBRIC_APPROVER_ROLES


class IsImporter(_RolePermission):
    roles = IMPORT_ROLES


def org_of(request):
    return request.membership.organisation


def get_for_org(queryset, organisation, **lookup):
    """Fetch one object inside the organisation, or 404 so nothing reveals that it exists."""
    obj = queryset.for_org(organisation).filter(**lookup).first()
    if obj is None:
        raise Http404
    return obj
