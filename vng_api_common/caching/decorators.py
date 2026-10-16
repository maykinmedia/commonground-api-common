import warnings
from collections.abc import Set as AbstractSet

from .conditional import conditional
from .registry import extract_dependencies


def conditional_retrieve(
    action: str = "retrieve",
    etag_field: str | None = None,
    extra_depends_on: AbstractSet[str] = frozenset(),
    variant_params: AbstractSet[str] = frozenset(),
):
    """
    Decorate a viewset to apply conditional GET requests.

    The handler of ``action`` sends the ETag of the resource's representation and
    answers a matching ``If-None-Match`` with 304. The serializer is introspected for
    the relations the representation reads, so writes to them invalidate the ETag.

    .. code-block:: python

        @conditional_retrieve(extra_depends_on={"rollen"}, variant_params={"expand"})
        class ZaakViewSet(viewsets.ReadOnlyModelViewSet): ...

    :param action: the viewset action to decorate
    :param etag_field: deprecated and ignored: ETags are stored in
      :class:`~vng_api_common.caching.models.StoredETag`
    :param extra_depends_on: model fields the representation reads that can't be
      introspected, such as those a ``SerializerMethodField`` reads
    :param variant_params: query parameters that select another representation, such
      as ``expand``; responses to requests with them get no ETag
    """

    if etag_field is not None:
        warnings.warn(
            "conditional_retrieve ignores etag_field", DeprecationWarning, stacklevel=2
        )

    def decorator(viewset: type):
        extract_dependencies(viewset, frozenset(extra_depends_on))
        handler = conditional(getattr(viewset, action), frozenset(variant_params))
        setattr(viewset, action, handler)
        # a new list, so a subclass doesn't add to its base's
        viewset._conditional_retrieves = [
            *getattr(viewset, "_conditional_retrieves", []),
            action,
        ]
        return viewset

    return decorator
