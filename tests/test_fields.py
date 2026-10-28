from django.core.exceptions import ValidationError

import pytest

from testapp.models import Medewerker
from vng_api_common.fields import URNField


def test_bsn_length():
    with pytest.raises(ValidationError):
        Medewerker(bsn="11122233").full_clean()

    with pytest.raises(ValidationError):
        Medewerker(bsn="1112223333").full_clean()

    Medewerker(bsn="111222333").full_clean()


def test_rsin_length():
    with pytest.raises(ValidationError):
        Medewerker(rsin="11122233").full_clean()

    with pytest.raises(ValidationError):
        Medewerker(rsin="1112223333").full_clean()

    Medewerker(rsin="111222333").full_clean()


@pytest.mark.parametrize("max_length", [255, 512])
def test_urn_field_length(max_length):
    field = URNField(max_length=max_length)
    value = "urn:example:".ljust(max_length, "a")

    assert field.max_length == max_length
    assert field.clean(value, None) == value
    with pytest.raises(ValidationError) as error:
        field.clean(value + "a", None)
    assert error.value.error_list[0].code == "max_length"


def test_urn_field_validation():
    field = URNField()

    assert field.clean("urn:example:document", None) == "urn:example:document"
    with pytest.raises(ValidationError) as error:
        field.clean("https://example.com/document", None)
    assert error.value.error_list[0].code == "invalid_urn"


@pytest.mark.parametrize(
    "kwargs", [{}, {"max_length": 512, "blank": True, "null": True}]
)
def test_urn_field_deconstruction(kwargs):
    field = URNField(**kwargs)

    _, path, args, reconstructed_kwargs = field.deconstruct()
    reconstructed = URNField(*args, **reconstructed_kwargs)

    assert path == "vng_api_common.fields.URNField"
    assert reconstructed.max_length == field.max_length
    assert reconstructed.blank == field.blank
    assert reconstructed.null == field.null
    assert reconstructed.validators == field.validators
