from django.core.exceptions import ValidationError
from django.db import models

import pytest

from testapp.models import Person
from vng_api_common.constants import FILTER_URL_DID_NOT_RESOLVE
from vng_api_common.filters import ListURNFilter, URLModelChoiceField, URNFilter
from vng_api_common.utils import NotAViewSet


def test_filter_field_url_to_pk_trailing_slash():
    field = URLModelChoiceField(queryset=Person.objects.all())
    with pytest.raises(NotAViewSet):
        field.url_to_pk("https://google.com/")


def test_filter_field_to_python_trailing_slash():
    field = URLModelChoiceField(queryset=Person.objects.all())
    value = field.to_python("https://google.com/")
    assert value == FILTER_URL_DID_NOT_RESOLVE


def test_filter_field_to_python_invalid_url_raises_error():
    field = URLModelChoiceField(queryset=Person.objects.all())
    with pytest.raises(ValidationError) as exc:
        field.to_python("thisisnotaurl")

    assert exc.value.code == "invalid"


@pytest.mark.parametrize("filter_class", [URNFilter, ListURNFilter])
@pytest.mark.parametrize("value", [None, "", [], (), {}])
def test_urn_filters_empty_value_leaves_queryset_unchanged(filter_class, value):
    queryset = Person.objects.all()

    assert filter_class(field_name="name").filter(queryset, value) is queryset


@pytest.mark.django_db
@pytest.mark.parametrize("exclude", [False, True])
@pytest.mark.parametrize("value", ["urn", "example", "42", "a.b+", "missing"])
def test_urn_filter_matches_whole_literal_segments(value, exclude):
    urns = [
        "urn:example:42",
        "urn:examples:142",
        "urn:example:a.b+",
        "urn:example:axb",
        "urn:Example:42extra",
    ]
    people = [Person.objects.create(name=urn) for urn in urns]
    queryset = Person.objects.all()

    result = URNFilter(field_name="name", exclude=exclude).filter(queryset, value)

    assert set(result) == {
        person for person in people if (value in person.name.split(":")) != exclude
    }


@pytest.mark.django_db
@pytest.mark.parametrize("json_key", [None, "reference"])
@pytest.mark.parametrize("exclude", [False, True])
@pytest.mark.parametrize("value", ["urn", "example", "42", "a.b+", "missing"])
def test_list_urn_filter_matches_supported_json_shapes(
    json_key, value, exclude, django_assert_num_queries
):
    key = json_key or "urn"
    rows = [
        (["urn:example:42", "urn:other:42"], {"urn", "example", "42"}),
        ([{key: "urn:example:a.b+", "label": "other"}], {"urn", "example", "a.b+"}),
        (["urn:examples:142", {key: "urn:other:axb"}], {"urn"}),
        ([None, "", {}, {"label": "urn:example:42"}], set()),
        ([], set()),
        (None, set()),
        ({key: "urn:example:42"}, set()),  # not a list
        ("urn:example:42", set()),  # not a list
    ]
    cases = []
    expected_pks = set()
    for items, matching_values in rows:
        person = Person.objects.create(name="test")
        cases.append(
            models.When(
                pk=person.pk,
                then=models.Value(items, output_field=models.JSONField()),
            )
        )
        if (value in matching_values) != exclude:
            expected_pks.add(person.pk)

    queryset = Person.objects.annotate(
        references=models.Case(*cases, output_field=models.JSONField())
    )
    kwargs = {"json_key": json_key} if json_key else {}
    urn_filter = ListURNFilter(field_name="references", exclude=exclude, **kwargs)

    with django_assert_num_queries(0):
        result = urn_filter.filter(queryset, value)

    with django_assert_num_queries(1):
        assert set(result.values_list("pk", flat=True)) == expected_pks
