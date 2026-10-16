"""
Calculate ETag values for API resources.
"""

import hashlib
from weakref import WeakKeyDictionary

from django.conf import settings
from django.db import models
from django.http import HttpRequest
from django.utils.module_loading import import_string

import structlog
from djangorestframework_camel_case.render import CamelCaseJSONRenderer
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.settings import api_settings

from ..utils import get_domain
from .registry import MODEL_SERIALIZERS

logger = structlog.stdlib.get_logger(__name__)

# entries are discarded when there are no hard references anymore to the model instance
weak_object_serializers_dict = WeakKeyDictionary()


def track_object_serializer(instance: models.Model, serializer: serializers.Serializer):
    """
    Track the serializer used for instance write.

    This is a performance optimization trick - if we can extract the serializer instance
    from the model instance used for the creation or update of the instance, we can
    avoid multiple serializer rounds. Additionally, the serializer should already
    contain context related to the request/domain.
    """
    existing = weak_object_serializers_dict.get(instance)
    if existing and existing != serializer:
        raise ValueError(
            "The instance is already tracking a different serializer for "
            "ETag calculation"
        )
    serializer_class = MODEL_SERIALIZERS[type(instance)]
    if not isinstance(serializer, serializer_class):
        raise TypeError(
            "Cannot track serializer %r, expected a %r instance."
            % (serializer, serializer_class)
        )

    weak_object_serializers_dict[instance] = serializer


class StaticRequest(HttpRequest):
    def get_host(self) -> str:
        return get_domain()

    def _get_scheme(self) -> str:
        return "https" if settings.IS_HTTPS else "http"


def get_etag_serializer(instance: models.Model) -> serializers.Serializer:
    serializer = weak_object_serializers_dict.get(instance)
    if serializer is not None:
        return serializer

    model_class = type(instance)
    serializer_class = MODEL_SERIALIZERS[model_class]

    # build a dummy request with the configured domain, since we're doing STRONG
    # comparison. Required as context for hyperlinked serializers
    request = Request(StaticRequest())
    request.version = api_settings.DEFAULT_VERSION  # type: ignore
    versioning_class = api_settings.DEFAULT_VERSIONING_CLASS
    if isinstance(versioning_class, str):
        versioning_class = import_string(versioning_class)
    request.versioning_scheme = versioning_class()  # pyright: ignore
    serializer = serializer_class(instance=instance, context={"request": request})
    return serializer  # type: ignore


def calculate_etag(instance: models.Model) -> str:
    """
    The ETag the API sends for ``instance`` as it is now, without the quotes.

    .. code-block:: python

        response = client.get(reverse("zaak-detail", kwargs={"uuid": zaak.uuid}))
        assert response["ETag"] == f'"{calculate_etag(zaak)}"'

    It serializes the instance, as a ``GET`` does: use it in tests and scripts, not
    in a loop of writes.
    """
    # the MD5 of the camelCase JSON the model's serializer renders
    serializer = get_etag_serializer(instance)

    # render the output to json, which is used as hash input
    renderer = CamelCaseJSONRenderer()
    rendered = renderer.render(serializer.data, "application/json")

    # calculate md5 hash
    return hashlib.md5(rendered).hexdigest()
