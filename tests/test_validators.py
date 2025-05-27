from datetime import datetime, timezone

from django.core.exceptions import ValidationError

import pytest
from freezegun import freeze_time

from vng_api_common.validators import (
    AlphanumericExcludingDiacritic,
    BaseIdentifierValidator,
    UntilNowValidator,
    validate_bsn,
    validate_rsin,
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
    validator = BaseIdentifierValidator(
        "296648875", identifier_length=9, validate_11proef=True
    )
    validator.validate()


def test_invalid_length():
    validator = BaseIdentifierValidator(
        "1234", identifier_length=9, validate_11proef=True
    )

    with pytest.raises(ValidationError) as error:
        validator.validate()
    assert "Waarde moet 9 tekens lang zijn" in str(error.value)


def test_invalid_isdigit():
    validator = BaseIdentifierValidator(
        "1234TEST", identifier_length=9, validate_11proef=True
    )

    with pytest.raises(ValidationError) as error:
        validator.validate()
    assert "Voer een numerieke waarde in" in str(error.value)


def test_invalid_11proefnumber():
    validator = BaseIdentifierValidator(
        "123456789", identifier_length=9, validate_11proef=True
    )
    with pytest.raises(ValidationError) as error:
        validator.validate()
    assert "Ongeldige code" in str(error.value)


def test_valid_bsn():
    validate_bsn("296648875")


def test_invalid_bsn():
    with pytest.raises(ValidationError) as error:
        validate_bsn("123456789")  # validate_11proef
    assert "Onjuist BSN nummer" in str(error.value)

    with pytest.raises(ValidationError) as error:
        validate_bsn("12345678")  # validate_length
    assert "Waarde moet 9 tekens lang zijn" in str(error.value)


def test_valid_rsin():
    validate_rsin("296648875")


def test_invalid_rsin():
    with pytest.raises(ValidationError) as error:
        validate_rsin("123456789")  # validate_11proef
    assert "Onjuist RSIN nummer" in str(error.value)

    with pytest.raises(ValidationError) as error:
        validate_rsin("12345678")  # validate_length
    assert "Waarde moet 9 tekens lang zijn" in str(error.value)


@freeze_time("2021-08-23T14:20:00")
def test_invalid_date():
    validator = UntilNowValidator()
    with pytest.raises(ValidationError) as error:
        validator(datetime(2021, 8, 23, 14, 20, 4, tzinfo=timezone.utc))
    assert "Ensure this value is not in the future." in str(error.value)


@freeze_time("2021-08-23T14:20:00")
def test_invalid_date_with_leeway(settings):
    settings.TIME_LEEWAY = 5
    validator = UntilNowValidator()
    validator(datetime(2021, 8, 23, 14, 20, 4, tzinfo=timezone.utc))
