from rest_framework import viewsets

from vng_api_common.filters_backend import Backend

from .serializers import NotitieSerializerMixin


class NotitieViewSetMixin(viewsets.ViewSet):
    """
    Mixin viewset for handling filtering and serialization of Notitie data.

    This mixin provides a base implementation for viewsets dealing with note-like
    objects, including standard filtering support on common fields.
    """

    serializer_class = NotitieSerializerMixin
    filter_backends = (Backend,)
    filterset_fields = {
        "onderwerp": ["exact", "icontains"],
        "tekst": ["exact", "icontains"],
        "aangemaakt_door": ["exact", "icontains"],
        "notitie_type": ["exact"],
        "status": ["exact"],
        "aanmaakdatum": ["exact", "gt", "lt", "gte", "lte"],
        "wijzigingsdatum": ["exact", "gt", "lt", "gte", "lte"],
        "gerelateerd_aan": ["exact"],
    }
