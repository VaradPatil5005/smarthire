"""Login throttling and invitations."""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.tenancy.models import Invitation, Membership


def _throttle_key(username, ip_address):
    # Account plus IP, so nobody elsewhere can lock out a named user. Hashed: no usernames in keys.
    digest = hashlib.sha256(f"{username.lower()}|{ip_address}".encode()).hexdigest()
    return f"login-failures:{digest}"


def is_throttled(username, ip_address) -> bool:
    return cache.get(_throttle_key(username, ip_address), 0) >= settings.LOGIN_THROTTLE_MAX_FAILURES


def record_failure(username, ip_address) -> None:
    key = _throttle_key(username, ip_address)
    cache.add(key, 0, settings.LOGIN_THROTTLE_WINDOW_SECONDS)
    cache.incr(key)


def clear_failures(username, ip_address) -> None:
    cache.delete(_throttle_key(username, ip_address))


def _hash_token(token) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_invitation(organisation, role, days=7) -> tuple[Invitation, str]:
    """Return the invitation and its raw token, which is shown once and never stored."""
    token = secrets.token_urlsafe(32)
    invitation = Invitation.objects.create(
        organisation=organisation,
        role=role,
        token_hash=_hash_token(token),
        expires_at=timezone.now() + timedelta(days=days),
    )
    return invitation, token


def find_usable_invitation(token):
    return Invitation.objects.filter(
        token_hash=_hash_token(token or ""),
        used_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).first()


@transaction.atomic
def redeem_invitation(invitation, user) -> Membership:
    """Single use. The role comes from the invitation, never from the form."""
    invitation = Invitation.objects.select_for_update().get(pk=invitation.pk)
    if invitation.used_at is not None:
        raise ValueError("Invitation already used")
    if invitation.expires_at <= timezone.now():
        raise ValueError("Invitation expired")
    invitation.used_at = timezone.now()
    invitation.save(update_fields=["used_at"])
    return Membership.objects.create(
        user=user, organisation=invitation.organisation, role=invitation.role
    )
