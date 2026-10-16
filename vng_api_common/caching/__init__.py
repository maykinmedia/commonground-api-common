"""
ETags and conditional ``GET`` requests: a client with the current version of a
resource gets a 304 instead of the body. The names below are the public API; the
rest of the package is implementation details.
"""

from .bulk import invalidate_all_etags, invalidate_etags, invalidating_update
from .decorators import conditional_retrieve
from .etags import calculate_etag
from .models import ETagMixin
from .store import batched_invalidation

# public API
__all__ = [
    "ETagMixin",
    "batched_invalidation",
    "calculate_etag",
    "conditional_retrieve",
    "invalidate_all_etags",
    "invalidate_etags",
    "invalidating_update",
]
