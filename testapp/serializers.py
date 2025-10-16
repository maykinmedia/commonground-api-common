from drf_extra_fields.fields import Base64FileField
from rest_framework import serializers
from rest_framework_gis.fields import GeometryField

from testapp.models import (
    FkModel,
    GeometryModel,
    Group,
    Hobby,
    MediaFileModel,
    Notitie,
    Person,
    Poly,
    PolyChoice,
    Record,
)
from vng_api_common.notes.api.serializers import NotitieSerializerMixin
from vng_api_common.polymorphism import Discriminator, PolymorphicSerializer
from vng_api_common.serializers import (
    CachedHyperlinkedIdentityField,
    CachedHyperlinkedRelatedField,
    CachedNestedHyperlinkedRelatedField,
    GegevensGroepSerializer,
)


class AddressSerializer(GegevensGroepSerializer):
    class Meta:
        model = Person
        gegevensgroep = "address"


class PersonSerializer(serializers.ModelSerializer):
    url = CachedHyperlinkedIdentityField(view_name="person-detail", lookup_field="pk")
    address = AddressSerializer(allow_null=True)
    group_name = serializers.SerializerMethodField()
    group_url = CachedHyperlinkedRelatedField(
        view_name="group-detail",
        source="group",
        lookup_field="pk",
        read_only=True,
    )

    class Meta:
        model = Person
        fields = (
            "url",
            "address",
            "name",
            "group_name",
            "group_url",
        )

    def get_group_name(self, obj) -> str:
        return obj.group.name if obj.group_id else ""


class PersonSerializer2(serializers.ModelSerializer):
    address = AddressSerializer(allow_null=True, required=False)
    address_not_null = AddressSerializer(
        allow_null=False, source="address", required=False
    )

    class Meta:
        model = Person
        fields = ("address", "address_not_null", "name")


class SubgroupSerializer(GegevensGroepSerializer):
    class Meta:
        model = Group
        gegevensgroep = "subgroup"


class GroupSerializer(serializers.ModelSerializer):
    persons = PersonSerializer(many=True, source="person_set")
    nested_persons = CachedNestedHyperlinkedRelatedField(
        many=True,
        view_name="nested-person-detail",
        parent_lookup_kwargs={"group_pk": "group__pk"},
        source="person_set",
        lookup_field="pk",
        read_only=True,
    )

    class Meta:
        model = Group
        fields = (
            "persons",
            "nested_persons",
        )


class MediaFileModelSerializer(serializers.ModelSerializer):
    file = Base64FileField(
        required=False,
        allow_null=True,
    )

    class Meta:
        model = MediaFileModel
        fields = ("file",)


class GeometryModelSerializer(serializers.ModelSerializer):
    geometry = GeometryField(required=False)

    class Meta:
        model = GeometryModel
        fields = ("geometry",)


# polymorphic serializer
class HobbySerializer(serializers.ModelSerializer):
    class Meta:
        model = Hobby
        fields = ("name", "people")


class RecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = Record
        fields = ("identificatie", "create_date")


class PolySerializer(PolymorphicSerializer):
    discriminator = Discriminator(
        discriminator_field="choice",
        mapping={
            PolyChoice.hobby: HobbySerializer(),
            PolyChoice.record: RecordSerializer(),
        },
        group_field="poly",
    )

    class Meta:
        model = Poly
        fields = ("name",)


class NotitieSerializer(NotitieSerializerMixin, serializers.ModelSerializer):
    class Meta(NotitieSerializerMixin.Meta):
        model = Notitie


class FkModelGegevensGroepSerializer(GegevensGroepSerializer):
    class Meta:
        model = FkModel
        gegevensgroep = "gegevensgroep"


class FkModelOptionalGegevensGroepSerializer(GegevensGroepSerializer):
    class Meta:
        model = FkModel
        gegevensgroep = "gegevensgroep_optional"


class FkModelAllowBlankGegevensGroepSerializer(GegevensGroepSerializer):
    class Meta:
        model = FkModel
        gegevensgroep = "gegevensgroep_allow_blank"


class FkModelSerializer(serializers.ModelSerializer):
    gegevensgroep = FkModelGegevensGroepSerializer(allow_null=True, required=False)
    gegevensgroep_optional = FkModelOptionalGegevensGroepSerializer(
        allow_null=True, required=False
    )
    gegevensgroep_allow_blank = FkModelAllowBlankGegevensGroepSerializer(
        allow_null=True, required=False
    )

    class Meta:
        model = FkModel
        fields = (
            "gegevensgroep",
            "gegevensgroep_optional",
            "gegevensgroep_allow_blank",
        )
