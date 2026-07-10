from typing import Any

from apps.audit.models import AuditLog


def create_audit_log(
    *,
    actor,
    action: str,
    target,
    metadata: dict[str, Any],
    correlation_id: str = "",
) -> AuditLog:
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        target_model=target.__class__.__name__,
        target_object_id=str(target.pk),
        target_repr=str(target),
        metadata=metadata,
        correlation_id=correlation_id,
    )
