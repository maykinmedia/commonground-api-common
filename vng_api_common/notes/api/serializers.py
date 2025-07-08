from rest_framework import serializers


class NotitieSerializerMixin(serializers.Serializer):
    class Meta:
        fields = (
            "onderwerp",
            "tekst",
            "aangemaakt_door",
            "notitie_type",
            "status",
            "aanmaakdatum",
            "wijzigingsdatum",
            "gerelateerd_aan",
        )
