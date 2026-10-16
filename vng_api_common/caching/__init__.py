"""
Facilitate HTTP caching mechanisms.

This package contains the tooling required to (efficiently) apply and use ETag
HTTP headers.

On a request level, the API will return HTTP 304 statuses if the client has
an up to date version of the resource. It will reply with a HTTP 200 otherwise,
including the ETag header.

This package provides a decorator to enable conditional requests on viewsets, and
``invalidating_update`` for a ``QuerySet.update``, which sends no signals. The model
mixin only keeps the ``_etag`` column of existing models. The rest are
implementation details.
"""

from .bulk import invalidating_update
from .decorators import conditional_retrieve
from .etags import calculate_etag
from .models import ETagMixin

# public API
__all__ = ["ETagMixin", "calculate_etag", "conditional_retrieve", "invalidating_update"]
