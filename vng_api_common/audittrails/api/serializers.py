from rest_framework import serializers

from ...constants import ComponentTypes
from ...serializers import GegevensGroepSerializer, add_choice_values_help_text
from ..models import AuditTrail


class WijzigingenSerializer(GegevensGroepSerializer):
    class Meta:
        model = AuditTrail
        gegevensgroep = "wijzigingen"


class AuditTrailSerializer(serializers.ModelSerializer):
    wijzigingen = WijzigingenSerializer()

    class Meta:
        model = AuditTrail
        fields = (
            "uuid",
            "bron",
            "applicatie_id",
            "applicatie_weergave",
            "gebruikers_id",
            "gebruikers_weergave",
            "actie",
            "actie_weergave",
            "resultaat",
            "hoofd_object",
            "resource",
            "resource_url",
            "toelichting",
            "resource_weergave",
            "aanmaakdatum",
            "wijzigingen",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        value_display_mapping = add_choice_values_help_text(ComponentTypes)
        self.fields["bron"].help_text += f"\n\n{value_display_mapping}"
        current_help = self.fields["bron"].help_text or ""
        self.fields["bron"].help_text = current_help + f"\n\n{value_display_mapping}"

        # Indicate that the values for AuditTrail.actie are not limited to
        # the CommonResourceActions
        custom_msg = """De bekende waardes voor dit veld zijn hieronder aangegeven, \
                        maar andere waardes zijn ook toegestaan"""

        current_help = self.fields["actie"].help_text or ""
        self.fields["actie"].help_text = (
            current_help + f"\n\n{custom_msg}\n\n{value_display_mapping}"
        )
