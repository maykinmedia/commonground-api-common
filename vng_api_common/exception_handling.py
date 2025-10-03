import uuid
from collections import OrderedDict
from typing import Any, Dict, Generator, List, Union

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from rest_framework import exceptions

from .serializers import FoutSerializer, ValidatieFoutSerializer
from .utils import underscore_to_camel

ErrorSerializer = FoutSerializer | ValidatieFoutSerializer

DEFAULT_CODE = "invalid"
DEFAULT_DETAIL = _("Invalid input.")
DEFAULT_STATUS = 400


def _translate_exceptions(exc):
    # Taken from DRF default exc handler
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied()
    return exc


def perform_list(
    errors: List[Any], field_name: str = ""
) -> Generator[OrderedDict, None, None]:
    """
    Handle the case when `errors` is a list.
    - Each item can be a dict, an ErrorDetail, or another nested structure.
    - Adds the index (e.g., `foo.0.bar`) to the error path.
    """
    for i, nested_error in enumerate(errors):
        for err in get_validation_errors(nested_error):
            if field_name:
                prefix = underscore_to_camel(field_name)
                err["name"] = (
                    f"{prefix}.{i}.{err['name']}" if err["name"] else f"{prefix}"
                )
            yield err


def perform_dict(
    errors: Dict[str, Any], field_name: str = ""
) -> Generator[OrderedDict, None, None]:
    """
    Handle the case when `errors` is a dictionary.
    - Each key represents a field, and each value represents sub-errors.
    - Propagates the parent field name (e.g., `parent.child`).
    """
    for sub_field, sub_errors in errors.items():
        for err in get_validation_errors(sub_errors, field_name=sub_field):
            prefix = underscore_to_camel(field_name)
            err["name"] = f"{prefix}.{err['name']}" if prefix else err["name"]
            yield err


def perform_detail(
    error: exceptions.ErrorDetail, field_name: str = ""
) -> Generator[OrderedDict, None, None]:
    """
    Handle the base case: a single ErrorDetail.
    - Returns an OrderedDict with keys: name, code, reason.
    """
    yield OrderedDict(
        [
            ("name", underscore_to_camel(field_name)),
            ("code", error.code),
            ("reason", str(error)),
        ]
    )


def get_validation_errors(
    errors: Union[List[Any], Dict[str, Any], exceptions.ErrorDetail, str],
    field_name: str = "",
) -> Generator[OrderedDict, None, None]:
    """
    Recursively flatten a `ValidationError.detail` structure
    into a uniform list of error objects.
    """
    if isinstance(errors, list):
        yield from perform_list(errors, field_name)
    elif isinstance(errors, dict):
        yield from perform_dict(errors, field_name)
    elif isinstance(errors, exceptions.ErrorDetail):
        yield from perform_detail(errors, field_name)


class HandledException:
    def __init__(self, exc: exceptions.APIException, response, request=None):
        self.exc = exc
        assert 400 <= response.status_code < 600, "Unsupported status code"
        self.response = response
        self.request = request

        self._exc_id = str(uuid.uuid4())

        try:
            import structlog
        except ImportError:
            self.logger = None
        else:
            structlog.contextvars.bind_contextvars(exception_id=self._exc_id)
            self.logger = structlog.stdlib.get_logger(__name__)

    @property
    def is_drf_exception(self):
        return isinstance(self.exc, exceptions.ValidationError)

    @property
    def _error_detail(self) -> str:
        if isinstance(self.exc, exceptions.ValidationError):
            # ErrorDetail from DRF is a str subclass
            data = getattr(self.response, "data", {})
            return data.get("detail", "")
        # any other exception -> return the raw ErrorDetails object so we get
        # access to the code later
        return self.exc.detail

    @classmethod
    def as_serializer(
        cls, exc: exceptions.APIException, response, request=None
    ) -> ErrorSerializer:
        """
        Return the appropriate serializer class instance.
        """
        exc = _translate_exceptions(exc)
        self = cls(exc, response, request)
        self.log()

        if isinstance(exc, exceptions.ValidationError):
            serializer_class = ValidatieFoutSerializer
        else:
            serializer_class = FoutSerializer

        return serializer_class(instance=self)

    def log(self):
        if self.logger and self.response.status_code < 500:
            self.logger.exception(
                "api.handled_exception",
                title=self.title,
                code=self.code,
                status=self.status,
                invalid_params=self.invalid_params,
                exc_info=False,
            )

    @property
    def type(self) -> str:
        exc_detail_url = reverse(
            "vng_api_common:error-detail",
            kwargs={"exception_class": self.exc.__class__.__name__},
        )
        if self.request is not None:
            exc_detail_url = self.request.build_absolute_uri(exc_detail_url)
        return exc_detail_url

    @property
    def code(self) -> str:
        """
        Return the generic code for this type of exception.
        """
        if self.is_drf_exception:
            return getattr(self.exc, "default_code", DEFAULT_CODE)
        return self._error_detail.code if self._error_detail else ""

    @property
    def title(self) -> str:
        """
        Return the generic title for this type of exception.
        """
        if self.is_drf_exception:
            return self.detail
        return getattr(self.exc, "default_detail", str(self._error_detail))

    @property
    def status(self) -> int:
        return getattr(self.response, "status_code", DEFAULT_STATUS)

    @property
    def detail(self) -> str:
        """
        Return the generic detail for this type of exception.
        """
        if self.is_drf_exception:
            return getattr(self.exc, "default_detail", DEFAULT_DETAIL)
        return str(self._error_detail)

    @property
    def instance(self) -> str:
        return f"urn:uuid:{self._exc_id}"

    @property
    def invalid_params(self) -> None | list:
        return [error for error in get_validation_errors(self.exc.detail)]
