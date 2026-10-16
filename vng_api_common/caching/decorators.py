import warnings
from collections.abc import Set as AbstractSet

from .conditional import conditional
from .registry import extract_dependencies


def conditional_retrieve(
    action: str = "retrieve",
    etag_field: str | None = None,
    extra_depends_on: AbstractSet[str] = frozenset(),
    *,
    variant_params: AbstractSet[str] = frozenset(),
):
    """
    Decorate a viewset to send ETags from its ``retrieve``, and to answer a matching
    ``If-None-Match`` with 304.


    The serializer is introspected for the relations the representation reads, so
    writes to them change the ETag.

    :param action: the viewset action to decorate
    :param etag_field: deprecated and ignored: ETags are stored in
      :class:`~vng_api_common.caching.models.StoredETag`
    :param extra_depends_on: model fields the representation reads that can't be
      introspected, such as those a ``SerializerMethodField`` reads
    :param variant_params: query parameters that select another representation, such
      as ``expand``; responses to requests with them get no ETag

    .. code-block:: python

        class ZaakSerializer(serializers.HyperlinkedModelSerializer):
            initiator = serializers.SerializerMethodField()

            def get_initiator(self, zaak) -> str:
                # reads the zaak's rollen, which no field of the serializer declares
                rol = zaak.rollen.filter(omschrijving_generiek="initiator").first()
                return rol.betrokkene if rol else ""


        # so a write to a rol changes the ETag of its zaak
        @conditional_retrieve(extra_depends_on={"rollen"}, variant_params={"expand"})
        class ZaakViewSet(viewsets.ReadOnlyModelViewSet):
            serializer_class = ZaakSerializer
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
