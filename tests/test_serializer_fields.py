import uuid

from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.test import override_settings

import pytest
from dateutil.relativedelta import relativedelta
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ErrorDetail

from vng_api_common.serializers import DurationField, URNRelatedField

VALID_DURATION_OPTIONS = [
    ("P10D", relativedelta(days=10)),
    ("P1M10D", relativedelta(months=1, days=10)),
    ("P1Y1M10D", relativedelta(years=1, months=1, days=10)),
    ("P-10D", relativedelta(days=-10)),
    ("P-1M-10D", relativedelta(months=-1, days=-10)),
    ("P-1Y-1M-10D", relativedelta(years=-1, months=-1, days=-10)),
    ("P1Y-1M10D", relativedelta(years=+1, months=-1, days=+10)),
]


class DurationSerializer(serializers.Serializer):
    duration = DurationField()


class DurationView(viewsets.ModelViewSet):
    serializer_class = DurationSerializer


def test_duration_field_valid_serialization():
    data = {"duration": ""}
    for duration in VALID_DURATION_OPTIONS:
        data["duration"] = duration[0]
        serializer = DurationSerializer(data=data)
        assert serializer.is_valid()
        assert serializer.to_representation({"duration": duration[1]}) == data


def test_duration_field_valid_deserialization():
    data = {"duration": ""}
    for duration in VALID_DURATION_OPTIONS:
        data["duration"] = duration[0]
        serializer = DurationSerializer(data=data)
        assert serializer.is_valid()
        assert serializer.to_internal_value(data) == {"duration": duration[1]}


def test_duration_field_invalid_deserialization():
    duration_options = [
        "test",
        "10D",
        "-P10D",
        "-P-10D",
    ]
    data = {"duration": ""}
    for d in duration_options:
        data["duration"] = d
        serializer = DurationSerializer(data=data)
        assert not serializer.is_valid()
        assert (
            serializer.errors["duration"][0]
            == "Duration has wrong format. Use one of these formats instead: P(n)Y(n)M(n)D."
        )


class ModelURN:
    def __init__(self, uuid):
        self.uuid = uuid


class QuerySetURNResource:
    def __init__(self, objects, lookup_field):
        self.objects = objects
        self.lookup_field = lookup_field

    def get(self, **kwargs):
        key, value = list(kwargs.items())[0]
        for obj in self.objects:
            if str(getattr(obj, key)) == value:
                return obj
        raise ObjectDoesNotExist()


class URNSerializer(serializers.Serializer):
    urn = URNRelatedField(
        view_name="resource:test-detail",
        urn_component="resource",
        urn_resource="test",
        lookup_field="uuid",
        required=True,
        queryset=QuerySetURNResource([], lookup_field="uuid"),
    )


@pytest.fixture
def urn_model():
    return ModelURN(uuid=uuid.uuid4())


@pytest.fixture
def urn_serializer(urn_model):
    return URNSerializer(instance=urn_model, context={"request": None})


def test_to_representation(urn_serializer, urn_model):
    field = urn_serializer.fields["urn"]

    urn = field.to_representation(urn_model)

    assert urn == f"urn:testapp:resource:test:{str(urn_model.uuid)}"


def test_to_internal_value(urn_serializer, urn_model):
    field = urn_serializer.fields["urn"]
    field.get_queryset = lambda: QuerySetURNResource([urn_model], lookup_field="uuid")

    value = f"urn:testapp:resource:test:{urn_model.uuid}"
    result = field.to_internal_value(value)

    assert result == urn_model


def test_required():
    serializer = URNSerializer(context={"request": None}, data={})

    assert not serializer.is_valid()

    assert serializer.errors == {
        "urn": [
            ErrorDetail(
                string="This field is required.",
                code="required",
            )
        ],
    }


def test_no_match():
    serializer = URNSerializer(
        context={"request": None},
        data={"urn": "test"},
    )

    assert not serializer.is_valid()

    assert serializer.errors == {
        "urn": [
            ErrorDetail(
                string="Invalid URN - Could not match the expected pattern.",
                code="no_match",
            )
        ]
    }


def test_incorrect_match():
    serializer = URNSerializer(
        context={"request": None},
        data={"urn": "urn:"},
    )

    assert not serializer.is_valid()

    assert serializer.errors == {
        "urn": [
            ErrorDetail(
                string="Invalid URN - Does not conform to the expected format.",
                code="incorrect_match",
            )
        ]
    }


def test_incorrect_match_uuid():
    serializer = URNSerializer(
        context={"request": None},
        data={"urn": "urn:test:test:1234"},
    )

    assert not serializer.is_valid()

    assert serializer.errors == {
        "urn": [
            ErrorDetail(
                string="Invalid URN - Does not conform to the expected format.",
                code="incorrect_match",
            )
        ]
    }


def test_incorrect_type():
    serializer = URNSerializer(
        context={"request": None},
        data={"urn": []},
    )

    assert not serializer.is_valid()

    assert serializer.errors == {
        "urn": [
            ErrorDetail(
                string="Incorrect type. Expected a string representing a URN, received list.",
                code="incorrect_type",
            )
        ]
    }


def test_does_not_exist():
    serializer = URNSerializer(
        context={"request": None},
        data={"urn": f"urn:testapp:resource:test:{uuid.uuid4()}"},
    )

    assert not serializer.is_valid()

    assert serializer.errors == {
        "urn": [
            ErrorDetail(
                string="Invalid URN - Corresponding object does not exist.",
                code="does_not_exist",
            )
        ]
    }


def test_urn_component_is_none(urn_serializer, urn_model):
    field = urn_serializer.fields["urn"]
    field.urn_component = None

    assert urn_serializer.context["request"] is None

    with pytest.raises(ImproperlyConfigured) as error:
        field.to_representation(urn_model)

    assert str(error.value) == (
        "URNRelatedField could not determine the `urn_component`:"
        " request, resolver_match, or namespace is missing in serializer context."
    )


def test_urn_resource_is_none(urn_serializer, urn_model):
    field = urn_serializer.fields["urn"]
    field.urn_resource = None

    assert urn_serializer.context["request"] is None

    with pytest.raises(ImproperlyConfigured) as error:
        field.to_representation(urn_model)

    assert str(error.value) == (
        "URNRelatedField could not determine the `urn_resource`: "
        "model not found on the view or serializer."
    )


def test_no_urn_match(urn_serializer):
    field = urn_serializer.fields["urn"]
    new_object = ModelURN(uuid=None)

    with pytest.raises(ImproperlyConfigured) as error:
        field.to_representation(new_object)

    assert str(error.value) == (
        "Could not resolve URN for the object using the configured view."
        " You may have failed to include the related model in your API, or"
        " incorrectly configured the `urn_component` or `urn_resource` for this field."
    )


def test_is_valid(urn_model):
    serializer = URNSerializer(
        context={"request": None},
        data={"urn": f"urn:testapp:resource:test:{urn_model.uuid}"},
    )
    serializer.fields["urn"].get_queryset = lambda: QuerySetURNResource(
        [urn_model], "uuid"
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["urn"] == urn_model


@pytest.mark.parametrize(
    "urn",
    [
        "urn:other:resource:test:{id}",
        "urn:testapp:other:test:{id}",
        "urn:testapp:resource:other:{id}",
        "urn:testapp:resource:test:garbage-{id}-trailing",
        "urn:testapp:resource:test:x y?{id}",
    ],
)
def test_rejects_wrong_resource_or_identifier(urn_model, urn):
    serializer = URNSerializer(data={"urn": urn.format(id=urn_model.uuid)})
    assert not serializer.is_valid()


@override_settings(COMMONGROUND_API_COMMON={"URN_NAMESPACE": None})
def test_empty_urn_namespace(urn_serializer, urn_model):
    with pytest.raises(ImproperlyConfigured) as error:
        field = urn_serializer.fields["urn"]
        field.to_representation(urn_model)

    assert str(error.value) == (
        "URNRelatedField requires a `urn_namespace` to be specified."
    )
