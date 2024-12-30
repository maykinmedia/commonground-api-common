from django.core.exceptions import ValidationError

import pytest

from vng_api_common.validators import (
    AlphanumericExcludingDiacritic,
    BaseValidator,
    validate_bsn,
)


@pytest.mark.parametrize("value", ["foo$", "aëeeei", "no spaces allowed"])
def test_alphanumeric_validator_error_invalid_input(value):
    validator = AlphanumericExcludingDiacritic()

    with pytest.raises(ValidationError):
        validator(value)


@pytest.mark.parametrize(
    "value",
    [
        "simple",
        "dashes-are-ok",
        "underscores_are_too",
        "let_us_not_forget_about_numb3rs",
    ],
)
def test_alphanumeric_validator_error_valid_input(value):
    validator = AlphanumericExcludingDiacritic()
    try:
        validator(value)
    except ValidationError:
        pytest.fail("Should have passed validation")


def test_equality_validator_instances():
    validator1 = AlphanumericExcludingDiacritic()
    validator2 = AlphanumericExcludingDiacritic()

    assert validator1 == validator2


def test_valid():
    validator = BaseValidator("296648875", list_size=[8, 9], check_11proefnumber=True)
    validator.validate()


def test_invalid_length():
    validator = BaseValidator("1234", list_size=[8, 9], check_11proefnumber=True)

    with pytest.raises(ValidationError) as error:
        validator.validate()
    assert (
        "De lengte van de waarde moet gelijk zijn aan een van deze waarden: [8, 9]"
        in str(error.value)
    )


def test_invalid_isdigit():
    validator = BaseValidator("1234TEST", list_size=[8, 9], check_11proefnumber=True)

    with pytest.raises(ValidationError) as error:
        validator.validate()
    assert "Voer een numerieke waarde in" in str(error.value)


def test_invalid_11proefnumber():
    validator = BaseValidator("123456789", list_size=[8, 9], check_11proefnumber=True)
    with pytest.raises(ValidationError) as error:
        validator.validate()
    assert "Ongeldige code" in str(error.value)


def test_valid_bsn():
    validate_bsn("296648875")


def test_invalid_bsn():
    with pytest.raises(ValidationError) as error:
        validate_bsn("123456789")
    assert "Onjuist BSN nummer" in str(error.value)
