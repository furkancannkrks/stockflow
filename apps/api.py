from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from apps.inventory.exceptions import InventoryDomainError
from apps.orders.exceptions import StockFlowDomainError


def error_response(code: str, message: str, details=None, status_code=status.HTTP_400_BAD_REQUEST):
    return Response(
        {
            "error": {
                "code": code,
                "message": message,
                "details": details or [],
            }
        },
        status=status_code,
    )


def domain_error_response(exc, status_code=status.HTTP_400_BAD_REQUEST):
    return error_response(exc.code, exc.message, exc.details, status_code=status_code)


def map_domain_exception(exc):
    if isinstance(exc, StockFlowDomainError):
        status_code = status.HTTP_409_CONFLICT
        if exc.code in {
            "DUPLICATE_ORDER_ITEM",
            "INVALID_CANCELLATION_SOURCE",
            "INVALID_ORDER_ITEM_QUANTITY",
        }:
            status_code = status.HTTP_400_BAD_REQUEST
        return domain_error_response(exc, status_code=status_code)

    if isinstance(exc, InventoryDomainError):
        status_code = status.HTTP_400_BAD_REQUEST
        if exc.code == "INVENTORY_NOT_FOUND":
            status_code = status.HTTP_404_NOT_FOUND
        return domain_error_response(exc, status_code=status_code)

    if isinstance(exc, DjangoValidationError):
        details = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
        return error_response(
            "VALIDATION_ERROR",
            "Submitted data is not valid.",
            details=details,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, DRFValidationError):
        return error_response(
            "VALIDATION_ERROR",
            "Submitted data is not valid.",
            details=exc.detail,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, IntegrityError):
        return error_response(
            "INTEGRITY_ERROR",
            "The request conflicts with existing data.",
            status_code=status.HTTP_409_CONFLICT,
        )

    if isinstance(exc, ProtectedError):
        return error_response(
            "PROTECTED_RESOURCE",
            "This resource is still referenced by other records.",
            status_code=status.HTTP_409_CONFLICT,
        )

    raise exc
