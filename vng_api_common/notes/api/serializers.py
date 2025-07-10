from rest_framework import serializers


class NotitieSerializerMixin(serializers.Serializer):
    """
    Mixin serializer for the Notitie model.

    This mixin defines a reusable set of fields commonly used for
    serializing data structures in the application.

    Note:
        The `gerelateerd_aan` field can be overridden depending on the
        specific object the Notitie is associated with.

    """

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
