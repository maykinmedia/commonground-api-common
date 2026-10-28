from datetime import datetime, timezone

from django.core.exceptions import ValidationError

import pytest
from freezegun import freeze_time

from vng_api_common.validators import (
    AlphanumericExcludingDiacritic,
    BaseIdentifierValidator,
    UntilNowValidator,
    URNValidator,
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
    validator = BaseIdentifierValidator("296648875", validate_11proef=True)
    validator.validate()


def test_invalid_isdigit():
    validator = BaseIdentifierValidator("1234TEST", validate_11proef=True)

    with pytest.raises(ValidationError) as error:
        validator.validate()
    assert "Voer een numerieke waarde in" in str(error.value)


def test_invalid_11proefnumber():
    validator = BaseIdentifierValidator("123456789", validate_11proef=True)
    with pytest.raises(ValidationError) as error:
        validator.validate()
    assert "Ongeldige code" in str(error.value)


def test_valid_bsn():
    validate_bsn("296648875")


def test_invalid_bsn():
    with pytest.raises(ValidationError) as error:
        validate_bsn("123456789")  # validate_11proef
    assert "Onjuist BSN nummer" in str(error.value)


def test_valid_rsin():
    validate_rsin("296648875")


def test_invalid_rsin():
    with pytest.raises(ValidationError) as error:
        validate_rsin("123456789")  # validate_11proef
    assert "Onjuist RSIN nummer" in str(error.value)


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


@pytest.mark.parametrize(
    "valid_urns",
    [
        "urn:isbn:9780143127796",
        "urn:uuid:123e4567-e89b-12d3-a456-426614174000",
        "urn:example:document/2026/12",
        "urn:maykin:abc:ztc:zaak:d42613cd-ee22-4455-808c-c19c7b8442a1",
        "urn:maykin:abc:ztc:zaak:abc:cde:123:456",
        "urn:isbn:abc%5E123",  # percent-encoded
        "urn:example-test:document@123",
        "urn:example:document-123.-_~",  # unreserved values
        "urn:example:document-123!$&'/*()+,;=",  # sub-delims values
        "urn:example:document:test@test",  # extra values
        "urn:example:document/123",
        "urn:example:document/123?+revision1",  # r_component
        "urn:example:document/123?=revision1",  # q_component
        "urn:example:document/123?+revision1?=query#section2",  # fragment
    ],
)
def test_valid_urn(valid_urns):
    validator = URNValidator()
    try:
        validator(valid_urns)
    except ValidationError:
        pytest.fail("Should have passed validation")


@pytest.mark.parametrize(
    "invalid_urns",
    [
        # missing 'urn:' prefix
        "isbn:9780143127796",
        "uuid:123e4567-e89b-12d3-a456-426614174000",
        # invalid NID
        "urn:-isbn:9780143127796",  # starts with '-'
        "urn:isbn-:9780143127796",  # ends with '-'
        "urn:123456789012345678901234567890123:abc",  # >32 chars
        "urn:£$%:123",
        "urn:in valid:123",
        "urn:!invalid:123",
        # invalid characters in NSS
        "urn:uuid",
        "urn:isbn:",
        "urn:isbn:abc^123",
        "urn:example:doc name",
        "urn:example:test?123",
        # invalid
        "urn::123",
        "urn:abc",
        "urn:",
    ],
)
def test_invalid_urn(invalid_urns):
    validator = URNValidator()
    with pytest.raises(ValidationError) as error:
        validator(invalid_urns)

    assert error.value.message == (
        "Enter a valid URN. Correct format: 'urn:<namespace>:<resource>' "
        "(e.g., urn:isbn:9780143127796)."
    )


def test_urn_validator_error():
    validator = URNValidator()

    with pytest.raises(ValidationError) as error:
        validator("invalid")

    assert error.value.message == validator.message
    assert error.value.code == "invalid_urn"
