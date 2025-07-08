from rest_framework import viewsets

from .serializers import NotitieSerializerMixin


class NotitieViewSetMixin(viewsets.ViewSet):
    serializer_class = NotitieSerializerMixin
    filterset_fields = [
        "onderwerp",
        "tekst",
        "aangemaakt_door",
        "notitie_type",
        "status",
        "aanmaakdatum",
        "wijzigingsdatum",
        "gerelateerd_aan",
    ]
