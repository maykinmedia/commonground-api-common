from types import SimpleNamespace
from unittest.mock import Mock

from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist

import pytest
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.relations import ObjectTypeError, ObjectValueError

from testapp.models import Folder, Group, Person, Sheet, Shortcut, Tag
from vng_api_common.serializers import (
    URNField,
    URNIdentityField,
    URNModelSerializer,
    URNRelatedField,
)


@pytest.mark.parametrize(
    ("exception", "expected"),
    [(ValueError, ObjectValueError), (TypeError, ObjectTypeError)],
)
def test_urn_related_field_get_object_with_invalid_lookup_value_throws_error(
    exception, expected
):
    queryset = Mock()
    queryset.get.side_effect = exception("Invalid lookup")
    field = URNRelatedField(queryset=queryset)

    with pytest.raises(expected, match="Invalid lookup") as error:
        field.get_object("pk", "invalid")

    assert isinstance(error.value.__cause__, exception)
    queryset.get.assert_called_once_with(pk="invalid")


@pytest.mark.parametrize(
    "exception", [ObjectValueError, ObjectTypeError, ObjectDoesNotExist]
)
def test_urn_related_field_to_internal_value_does_not_exist_throws_error(exception):
    queryset = Mock()
    queryset.get.side_effect = exception("Invalid lookup")
    field = URNRelatedField(
        queryset=queryset,
        lookup_field="uuid",
        urn_component="api",
        urn_resource="resource",
    )

    with pytest.raises(ValidationError) as error:
        field.to_internal_value(
            "urn:testapp:api:resource:12345678-1234-1234-1234-123456789abc"
        )
    assert error.value.get_codes() == ["does_not_exist"]


def test_urn_identity_field_extract_urn_component_and_resource_from_context():
    class GroupSerializer(serializers.Serializer):
        urn = URNIdentityField()

    group = Group(pk=42, name="Example")
    serializer = GroupSerializer(
        group,
        context={
            "request": SimpleNamespace(
                resolver_match=SimpleNamespace(namespace="groups")
            ),
            "view": SimpleNamespace(queryset=Group.objects.all()),
        },
    )

    assert serializer.data == {"urn": "urn:testapp:groups:group:42"}


@pytest.mark.parametrize("namespace", [None, ""])
def test_urn_identity_field_get_urn_component_empty_context_namespace_throws_error(
    namespace,
):
    field = URNIdentityField()
    field._context = {
        "request": SimpleNamespace(resolver_match=SimpleNamespace(namespace=namespace))
    }

    with pytest.raises(
        ImproperlyConfigured, match="could not determine the `urn_component`"
    ):
        field.get_urn_component()


def test_urn_identity_field_get_urn_resource_empty_model_name_throws_error():
    field = URNIdentityField()
    field._context = {
        "view": SimpleNamespace(
            queryset=SimpleNamespace(
                model=SimpleNamespace(_meta=SimpleNamespace(model_name=""))
            )
        )
    }

    with pytest.raises(
        ImproperlyConfigured, match="could not determine the `urn_resource`"
    ):
        field.get_urn_resource()


@pytest.mark.parametrize("pk", [None, ""])
def test_urn_identity_field_has_no_urn_does_not_exist(pk):
    field = URNIdentityField()

    assert field.get_urn(Group(pk=pk)) is None


def test_urn_identity_field_accepts_explicit_namespace():
    field = URNIdentityField(
        urn_namespace="explicit", urn_component="groups", urn_resource="group"
    )

    assert field.to_representation(Group(pk=42)) == "urn:explicit:groups:group:42"


def test_urn_identity_field_is_read_only_and_uses_whole_object():
    field = URNIdentityField()

    assert field.read_only is True
    assert field.source == "*"
    assert field.use_pk_only_optimization() is False


def test_urn_model_serializer_builds_default_fields():
    class PersonSerializer(URNModelSerializer):
        label = serializers.CharField(source="name")

        class Meta:
            model = Person
            fields = "__all__"
            depth = 1

    serializer = PersonSerializer()

    assert list(serializer.fields) == [
        "urn",
        "label",
        "_etag",
        "name",
        "address_street",
        "address_number",
        "group",
        "hobbies",
    ]
    assert isinstance(serializer.fields["urn"], URNIdentityField)
    assert serializer.fields["urn"].view_name == "person-detail"
    assert isinstance(serializer.fields["name"], serializers.CharField)


def test_urn_model_serializer_builds_nested_relations():
    class PersonSerializer(URNModelSerializer):
        class Meta:
            model = Person
            fields = ("urn", "group")
            depth = 1

    serializer = PersonSerializer()
    field = serializer.fields["group"]

    assert isinstance(field, URNModelSerializer)
    assert field.Meta.model is Group
    assert field.Meta.depth == 0
    assert field.read_only is True
    assert isinstance(field.fields["urn"], URNIdentityField)
    assert isinstance(field.fields["name"], serializers.CharField)


@pytest.mark.parametrize(
    "value", ["urn:example:resource:42", "urn:example:resource:abc"]
)
def test_urn_field_accepts_valid_urn(value):
    assert URNField().run_validation(value) == value


def test_urn_field_rejects_invalid_urn():
    with pytest.raises(ValidationError) as error:
        URNField().run_validation("https://example.com/resource/42")

    assert error.value.get_codes() == ["invalid_urn"]


def urn_model_serializer(model_class, levels):
    class RowSerializer(URNModelSerializer):
        class Meta:
            model = model_class
            fields = "__all__"
            depth = levels

    return RowSerializer


def tag_of(folder):
    tag = Tag.objects.create(pk=3, label="t")
    tag.folders.set([folder])
    return tag


def urns(shown):
    """A relation's output, with nested objects reduced to their own URN."""
    match shown:
        case list():
            return [urns(item) for item in shown]
        case dict():
            return shown["urn"]
        case _:
            return shown


FOLDER = "urn:testapp:api:folder:7"


@pytest.mark.django_db
@pytest.mark.parametrize("depth", [0, 1])
@pytest.mark.parametrize(
    "make_row, relation, urn, related",
    [
        pytest.param(
            lambda folder: Sheet.objects.create(
                pk=3, folder=folder, title="t", position=0
            ),
            "folder",
            "urn:testapp:api:sheet:3",
            FOLDER,
            id="fk",
        ),
        pytest.param(tag_of, "folders", "urn:testapp:api:tag:3", [FOLDER], id="m2m"),
        pytest.param(
            lambda folder: Shortcut.objects.create(pk=3, label="s", target=folder),
            "target",
            "urn:testapp:api:shortcut:3",
            FOLDER,
            id="nullable-fk",
        ),
        pytest.param(
            lambda folder: Shortcut.objects.create(pk=3, label="s", target=None),
            "target",
            "urn:testapp:api:shortcut:3",
            None,
            id="nullable-fk-empty",
        ),
    ],
)
def test_urn_model_serializer_names_each_model(depth, make_row, relation, urn, related):
    row = make_row(Folder.objects.create(pk=7, name="f", code="c"))
    serializer = urn_model_serializer(type(row), depth)

    data = serializer(row, context=context_of_a_view_on(type(row))).data

    assert data["urn"] == urn
    assert urns(data[relation]) == related


def context_of_a_view_on(model):
    return {
        "request": SimpleNamespace(resolver_match=SimpleNamespace(namespace="api")),
        "view": SimpleNamespace(queryset=model.objects.all()),
    }


def test_a_relation_names_the_related_model():
    class SheetSerializer(serializers.Serializer):
        folder = URNRelatedField(queryset=Folder.objects.all())

    sheet = Sheet(pk=3, folder=Folder(pk=7))
    data = SheetSerializer(sheet, context=context_of_a_view_on(Sheet)).data
    assert data["folder"] == "urn:testapp:api:folder:7"


def test_zero_primary_key_round_trip():
    queryset = Mock()
    queryset.get.return_value = Folder(pk=0)
    field = URNRelatedField(
        queryset=queryset, urn_component="api", urn_resource="folder"
    )
    assert field.to_representation(Folder(pk=0)) == "urn:testapp:api:folder:0"
    assert field.run_validation("urn:testapp:api:folder:0").pk == 0
    queryset.get.assert_called_once_with(pk="0")


def test_existing_model_urn_field_is_rejected():
    class PersonSerializer(URNModelSerializer):
        urn_field_name = "name"

        class Meta:
            model = Person
            fields = "__all__"

    with pytest.raises(ImproperlyConfigured, match="already defines"):
        PersonSerializer().fields
