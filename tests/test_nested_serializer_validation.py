import pytest

from testapp.serializers import GroupSerializer
from vng_api_common.exception_handling import get_validation_errors


def test_create_invalid_params():
    """
    Test that nested validation works as expected.

    Original validation errors:

    {
        'person': [
            {
            },
            {
                'address': {
                    'street': [
                        ErrorDetail(string='This field is required.', code='required')
                    ]
                }
            }, {
                'name': [
                    ErrorDetail(string='This field is required.', code='required')
                ]
            }
        ]
    }

    Expected converted validation errors (`dict`'s are actually `OrderedDict`'s):

    [
        {
            'name': 'person.1.address.street',
            'code': 'required',
            'reason': 'This field is required.'
        }
        {
            'name': 'person.2.name',
            'code': 'required',
            'reason': 'This field is required.'
        }
    ]
    """
    serializer = GroupSerializer(
        data={
            "persons": [
                {
                    "name": "john",
                    "address": {"street": "Keizersgracht", "number": "416"},
                },
                {"name": "jane", "address": {"number": "117"}},
                {"address": {"street": "Herengracht", "number": "100"}},
            ]
        },
        partial=False,
    )

    assert not serializer.is_valid()

    validation_errors = list(get_validation_errors(serializer.errors))

    assert validation_errors[0]["name"] == "persons.1.address.street"
    assert validation_errors[0]["code"] == "required"

    assert validation_errors[1]["name"] == "persons.2.name"
    assert validation_errors[1]["code"] == "required"


def test_create_valid():
    serializer = GroupSerializer(
        data={
            "persons": [
                {
                    "name": "test",
                    "address": {"street": "Keizersgracht", "number": "117"},
                },
                {
                    "name": "test2",
                    "address": {"street": "Herengracht", "number": "100"},
                },
            ]
        },
        partial=False,
    )

    assert serializer.is_valid()


def test_create_invalid_params_first_item_invalid():
    """
    DRF 3.18 reports list-serializer errors as a dict keyed by index. Errors for
    the first item (index ``0``) must keep their index in the parameter name.
    """
    serializer = GroupSerializer(
        data={"persons": [{"name": "john", "address": {"number": "416"}}]},
        partial=False,
    )

    assert not serializer.is_valid()

    validation_errors = list(get_validation_errors(serializer.errors))

    assert [error["name"] for error in validation_errors] == [
        "persons.0.address.street"
    ]


@pytest.mark.filterwarnings("ignore:The list-based error format")
@pytest.mark.parametrize("errors_as_dict", (True, False))
def test_create_invalid_params_list_serializer_error_formats(settings, errors_as_dict):
    """
    The parameter names must be identical for the dict (DRF 3.18+ default) and
    the list (DRF < 3.18, or ``LIST_SERIALIZER_ERRORS_AS_DICT = False``) formats.
    """
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "LIST_SERIALIZER_ERRORS_AS_DICT": errors_as_dict,
    }
    serializer = GroupSerializer(
        data={
            "persons": [
                {"name": "john", "address": {"number": "416"}},
                {"name": "jane", "address": {"street": "Herengracht", "number": "1"}},
                {"address": {"street": "Herengracht", "number": "100"}},
            ]
        },
        partial=False,
    )

    assert not serializer.is_valid()

    validation_errors = list(get_validation_errors(serializer.errors))

    assert [error["name"] for error in validation_errors] == [
        "persons.0.address.street",
        "persons.2.name",
    ]
