from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.tenancy.models import TenantModel


class AuditEvent(TenantModel):
    """Who did what to which object. IDs and actions only, never document or contact text."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    action = models.CharField(max_length=64)
    object_type = models.CharField(max_length=64)
    object_id = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return f"{self.action} {self.object_type} {self.object_id}"


def record_event(organisation, actor, action, obj) -> AuditEvent:
    return AuditEvent.objects.create(
        organisation=organisation,
        actor=actor,
        action=action,
        object_type=type(obj).__name__,
        object_id=str(obj.pk),
    )
