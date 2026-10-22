from django.utils.translation import gettext_lazy as _

from rest_framework import status
from rest_framework.exceptions import APIException


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = _("A conflict occurred")
    default_code = "conflict"


class Gone(APIException):
    status_code = status.HTTP_410_GONE
    default_detail = _("The resource is gone")
    default_code = "gone"


class PreconditionFailed(APIException):
    status_code = status.HTTP_412_PRECONDITION_FAILED
    default_detail = _("Precondition failed")
    default_code = "precondition_failed"


class TransactionCancelled(APIException):
    """
    PostgreSQL cancelled the request's transaction to resolve a deadlock or a
    serialization conflict with another one. Nothing of it was written, so a
    retry most likely succeeds.
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = _(
        "The request conflicted with another one and was cancelled. Try again."
    )
    default_code = "transaction_cancelled"
    wait = 1  # sent as Retry-After
