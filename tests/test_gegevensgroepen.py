import pytest
from rest_framework.test import APIRequestFactory

from testapp.models import FkModel, Group, Person
from testapp.serializers import (
    FkModelSerializer,
    PersonSerializer,
    PersonSerializer2,
)


def test_partial_serializer_validation_gegevensgroep_invalid():
    serializer = PersonSerializer(
        data={"address": {"street": "Keizersgracht"}}, partial=True
    )

    assert not serializer.is_valid()


def test_partial_serializer_validation_gegevensgroep_valid():
    serializer = PersonSerializer(
        data={"address": {"street": "Keizersgracht", "number": "117"}}, partial=True
    )

    assert serializer.is_valid()


def test_partial_serializer_validation_gegevensgroep_valid2():
    serializer = PersonSerializer(data={"name": "Willy De Kooning"}, partial=True)

    assert serializer.is_valid()


def test_partial_serializer_validation_gegevensgroep_null():
    serializer = PersonSerializer(
        data={"name": "Willy De Kooning", "address": None}, partial=True
    )

    assert serializer.is_valid()


def test_full_serializer_gegevensgroep_null():
    serializer = PersonSerializer2(
        data={"name": "Willy De Kooning", "address": None}, partial=False
    )

    assert serializer.is_valid()


def test_full_serializer_validation_gegevensgroep_valid():
    serializer = PersonSerializer(
        data={
            "name": "Willy De Kooning",
            "address": {"street": "Keizersgracht", "number": "117"},
        },
        partial=False,
    )

    assert serializer.is_valid()


def test_full_serializer_validation_gegevensgroep_valid2():
    serializer = PersonSerializer(
        data={"address": {"street": "Keizersgracht", "number": "117"}}, partial=False
    )

    assert not serializer.is_valid()


def test_full_serializer_validation_gegevensgroep_invalid():
    serializer = PersonSerializer(
        data={"name": "Willy De Kooning", "address": {"street": "Keizersgracht"}},
        partial=False,
    )

    assert not serializer.is_valid()


def test_gegevensgroep_serializer_nested_error_message():
    serializer = PersonSerializer(
        data={"name": "Willy De Kooning", "address": {"street": "Keizersgracht"}},
        partial=False,
    )

    serializer.is_valid()
    errors = serializer.errors

    assert "address" in errors
    assert "number" in errors["address"]
    assert errors["address"]["number"][0].code == "required"


def test_assignment_missing_optional_key():
    group = Group(subgroup_field_2="")
    group.subgroup = {"field_1": "foo"}

    assert group.subgroup_field_1 == "foo"
    assert group.subgroup_field_2 == "baz"


def test_nullable_and_empty_gegevensgroep_with_fields_that_do_not_allow_blank_returned_as_null():
    person = Person(name="bla", address_street="", address_number="")
    factory = APIRequestFactory()
    request = factory.get("/persons")
    output = PersonSerializer(context={"request": request}).to_representation(
        instance=person
    )
    assert output["address"] is None


def test_nullable_and_not_fully_empty_gegevensgroep_with_fields_that_do_not_allow_blank_not_returned_as_null():
    person = Person(name="bla", address_street="kerkstraat", address_number="")
    factory = APIRequestFactory()
    request = factory.get("/persons")
    output = PersonSerializer(context={"request": request}).to_representation(
        instance=person
    )
    assert output["address"] == {
        "street": "kerkstraat",
        "number": "",
    }


def test_not_nullable_and_empty_gegevensgroep_not_returned_as_null():
    person = Person(name="bla", address_street="", address_number="")
    factory = APIRequestFactory()
    request = factory.get("/persons")
    output = PersonSerializer2(context={"request": request}).to_representation(
        instance=person
    )
    assert output["address_not_null"] == {
        "street": "",
        "number": "",
    }


def test_not_nullable_and_not_empty_gegevensgroep_not_returned_as_null():
    person = Person(name="bla", address_street="", address_number="10")
    factory = APIRequestFactory()
    request = factory.get("/persons")
    output = PersonSerializer2(context={"request": request}).to_representation(
        instance=person
    )
    assert output["address_not_null"] == {
        "street": "",
        "number": "10",
    }


@pytest.mark.django_db
def test_nullable_and_empty_gegevensgroep_with_fields_that_allow_blank_not_returned_as_null():
    person = FkModel(pk=1)
    factory = APIRequestFactory()
    request = factory.get("/persons")
    output = FkModelSerializer(context={"request": request}).to_representation(
        instance=person
    )
    assert output["gegevensgroep_allow_blank"] == {
        "attribute1": "",
    }


@pytest.mark.django_db
def test_nullable_and_not_fully_empty_gegevensgroep_with_fields_that_allow_blank_not_returned_as_null():
    person = FkModel(pk=1, attribute1="foo")
    factory = APIRequestFactory()
    request = factory.get("/persons")
    output = FkModelSerializer(context={"request": request}).to_representation(
        instance=person
    )
    assert output["gegevensgroep_allow_blank"] == {
        "attribute1": "foo",
    }


def test_required_choicefields_do_not_allow_blank():
    factory = APIRequestFactory()
    request = factory.get("/persons")
    serializer = FkModelSerializer(
        context={"request": request}, data={"gegevensgroep": {"attribute2": ""}}
    )

    assert not serializer.is_valid()
    assert serializer.errors["gegevensgroep"]["attribute2"][0].code == "invalid_choice"


def test_optional_choicefields_allow_blank():
    factory = APIRequestFactory()
    request = factory.get("/persons")
    serializer = FkModelSerializer(
        context={"request": request},
        data={"gegevensgroep_optional": {"attribute2": ""}},
    )

    assert serializer.is_valid()


def test_required_charfields_allow_blank():
    factory = APIRequestFactory()
    request = factory.get("/persons")
    serializer = FkModelSerializer(
        context={"request": request},
        data={"gegevensgroep": {"attribute1": "", "attribute2": "op1"}},
    )

    assert serializer.is_valid()
