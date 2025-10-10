from django.core.exceptions import ValidationError

import pytest

from testapp.models import Medewerker


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
