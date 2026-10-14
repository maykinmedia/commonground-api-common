from collections.abc import Set as AbstractSet

from django.db.models import Manager, Model

from drf_extra_fields.fields import Base64FileField
from rest_framework import serializers
from rest_framework_gis.fields import GeometryField

from testapp.checkpoints import checkpoint
from testapp.models import (
    Attachment,
    FkModel,
    Folder,
    GeometryModel,
    Group,
    Hobby,
    MediaFileModel,
    Notitie,
    Person,
    Poly,
    PolyChoice,
    Record,
    Sheet,
    Shortcut,
    Tag,
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


# ETag tests (tests/test_etag_*.py)


class ExpandingSerializer(serializers.ModelSerializer):
    """
    Adds the representations of the related resources a request names in the
    view's ``expand_param`` under ``_expand``, the way Open Zaak's ``?expand=``
    does. Without a view, as when calculating the ETag, nothing is expanded.
    """

    expandable: AbstractSet[str] = frozenset()

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        view = self.context.get("view")
        if view is None or self.context.get("expanding"):
            return representation
        requested = view.request.query_params.get(view.expand_param, "").split(",")
        if names := [name for name in requested if name in self.expandable]:
            context = {**self.context, "expanding": True}
            representation["_expand"] = {
                name: expand(instance, name, context) for name in names
            }
        return representation


def expand(instance: Model, name: str, context: dict[str, object]) -> object:
    related = getattr(instance, name)
    if related is None:
        return None
    if isinstance(related, Manager):
        serializer_class = SERIALIZERS[related.model]
        return serializer_class(related.all(), many=True, context=context).data
    return SERIALIZERS[type(related)](related, context=context).data


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = ["filename"]


class FolderSerializer(ExpandingSerializer):
    url = CachedHyperlinkedIdentityField(view_name="folder-detail", lookup_field="pk")
    sheets = CachedHyperlinkedRelatedField(
        view_name="sheet-detail", lookup_field="pk", many=True, read_only=True
    )
    tags = CachedHyperlinkedRelatedField(
        view_name="tag-detail", lookup_field="pk", many=True, read_only=True
    )
    attachments = AttachmentSerializer(many=True, read_only=True)
    first_sheet_title = serializers.SerializerMethodField()

    expandable = frozenset({"sheets", "tags"})

    class Meta:
        model = Folder
        fields = [
            "url",
            "name",
            "code",
            "sheets",
            "tags",
            "attachments",
            "first_sheet_title",
        ]

    def get_first_sheet_title(self, obj) -> str:
        first = obj.sheets.first()
        return first.title if first else ""

    def to_representation(self, instance):
        checkpoint()  # tests/test_etag_concurrency.py may pause before the reads
        representation = super().to_representation(instance)
        checkpoint()  # or after them
        return representation


class SheetSerializer(ExpandingSerializer):
    url = CachedHyperlinkedIdentityField(view_name="sheet-detail", lookup_field="pk")
    folder = CachedHyperlinkedRelatedField(
        view_name="folder-detail", lookup_field="pk", read_only=True
    )
    folder_code = serializers.SlugRelatedField(
        source="folder", slug_field="code", read_only=True
    )

    expandable = frozenset({"folder"})

    class Meta:
        model = Sheet
        fields = ["url", "title", "position", "folder", "folder_code"]


class TagSerializer(ExpandingSerializer):
    url = CachedHyperlinkedIdentityField(view_name="tag-detail", lookup_field="pk")
    folders = CachedHyperlinkedRelatedField(
        view_name="folder-detail", lookup_field="pk", many=True, read_only=True
    )

    expandable = frozenset({"folders"})

    class Meta:
        model = Tag
        fields = ["url", "label", "folders"]


class ShortcutSerializer(ExpandingSerializer):
    url = CachedHyperlinkedIdentityField(view_name="shortcut-detail", lookup_field="pk")
    target = CachedHyperlinkedRelatedField(
        view_name="folder-detail", lookup_field="pk", read_only=True
    )

    expandable = frozenset({"target"})

    class Meta:
        model = Shortcut
        fields = ["url", "label", "target"]


SERIALIZERS: dict[type[Model], type[serializers.ModelSerializer]] = {
    Folder: FolderSerializer,
    Sheet: SheetSerializer,
    Tag: TagSerializer,
    Shortcut: ShortcutSerializer,
}
