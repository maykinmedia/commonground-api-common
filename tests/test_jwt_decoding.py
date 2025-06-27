from datetime import datetime

import jwt
import pytest
from freezegun import freeze_time
from rest_framework.exceptions import PermissionDenied

from vng_api_common.authorizations.middleware import JWTAuth
from vng_api_common.models import JWTSecret


@pytest.mark.django_db
def test_jwt_decode_ok():
    secret = "secret"
    JWTSecret.objects.create(identifier="client", secret=secret)
    timestamp = int(datetime.now().timestamp())
    token = jwt.encode(
        {"client_id": "client", "iat": timestamp}, secret, algorithm="HS256"
    )

    auth = JWTAuth(token)

    payload = auth.payload
    assert auth.client_id == "client"
    assert payload == {"client_id": "client", "iat": timestamp}


@pytest.mark.django_db
def test_jwt_decode_missing_iat():
    secret = "secret"
    JWTSecret.objects.create(identifier="client", secret=secret)
    token = jwt.encode({"client_id": "client"}, secret, algorithm="HS256")

    auth = JWTAuth(token)

    with pytest.raises(PermissionDenied):
        auth.payload


@pytest.mark.django_db
def test_jwt_decode_str_iat():
    JWTSecret.objects.create(identifier="client", secret="secret")
    payload = {
        "client_id": "client",
        "iat": "timestamp",
    }
    token = jwt.encode(payload, "secret", algorithm="HS256")

    auth = JWTAuth(token)

    with pytest.raises(PermissionDenied):
        auth.payload


@pytest.mark.django_db
@freeze_time("2021-08-23T14:20:00")
def test_nbf_validated():
    JWTSecret.objects.create(identifier="client", secret="secret")
    timestamp = int(datetime.now().timestamp())
    payload = {
        "client_id": "client",
        "iat": timestamp,
        "nbf": timestamp + 1,  # 1 second "later" than current time
    }
    token = jwt.encode(payload, "secret", algorithm="HS256")

    auth = JWTAuth(token)

    with pytest.raises(PermissionDenied):
        auth.payload


@pytest.mark.django_db
@freeze_time("2021-08-23T14:20:00")
def test_nbf_validated_with_leeway(settings):
    settings.TIME_LEEWAY = 3
    JWTSecret.objects.create(identifier="client", secret="secret")
    timestamp = int(datetime.now().timestamp())
    payload = {
        "client_id": "client",
        "iat": timestamp,
        "nbf": timestamp + 1,  # 1 second "later" than current time
    }
    token = jwt.encode(payload, "secret", algorithm="HS256")

    auth = JWTAuth(token)

    assert auth.payload == payload


@pytest.mark.django_db
@freeze_time("2021-08-23T14:20:00")
def test_nbf_validated_with_leeway_not_enough(settings):
    settings.TIME_LEEWAY = 3
    JWTSecret.objects.create(identifier="client", secret="secret")
    timestamp = int(datetime.now().timestamp())
    payload = {
        "client_id": "client",
        "iat": timestamp,
        "nbf": timestamp + 10,  # 1 second "later" than current time
    }
    token = jwt.encode(payload, "secret", algorithm="HS256")

    auth = JWTAuth(token)

    with pytest.raises(PermissionDenied):
        auth.payload


@pytest.mark.django_db
@freeze_time("2021-08-23T14:20:00")
def test_iat_validated():
    """jwt iat in future only logs a warning"""
    JWTSecret.objects.create(identifier="client", secret="secret")
    timestamp = int(datetime.now().timestamp())
    payload = {
        "client_id": "client",
        "iat": timestamp + 1,  # 1 second "later" than current time
    }
    token = jwt.encode(payload, "secret", algorithm="HS256")

    auth = JWTAuth(token)

    assert auth.payload == payload


@pytest.mark.django_db
@freeze_time("2021-08-23T14:20:00")
def test_iat_validated_with_leeway(settings):
    settings.TIME_LEEWAY = 3
    JWTSecret.objects.create(identifier="client", secret="secret")
    timestamp = int(datetime.now().timestamp())
    payload = {
        "client_id": "client",
        "iat": timestamp + 1,  # 1 second "later" than current time
    }
    token = jwt.encode(payload, "secret", algorithm="HS256")

    auth = JWTAuth(token)

    assert auth.payload == payload


@pytest.mark.django_db
@freeze_time("2021-08-23T14:20:00")
def test_iat_validated_with_leeway_not_enough(settings):
    """jwt iat in future only logs a warning"""
    settings.TIME_LEEWAY = 3
    JWTSecret.objects.create(identifier="client", secret="secret")
    timestamp = int(datetime.now().timestamp())
    payload = {
        "client_id": "client",
        "iat": timestamp + 10,  # 1 second "later" than current time
    }
    token = jwt.encode(payload, "secret", algorithm="HS256")

    auth = JWTAuth(token)

    assert auth.payload == payload


@pytest.mark.django_db
@freeze_time("2021-08-23T14:20:00")
def test_exp_ok():
    JWTSecret.objects.create(identifier="client", secret="secret")
    timestamp = int(datetime.now().timestamp())
    payload = {"client_id": "client", "iat": timestamp}
    token = jwt.encode(payload, "secret", algorithm="HS256")

    auth = JWTAuth(token)

    assert auth.payload == payload


@pytest.mark.django_db
@freeze_time("2021-08-23T14:20:00")
def test_exp_within_exp_setting():
    JWTSecret.objects.create(identifier="client", secret="secret")
    timestamp = int(datetime.now().timestamp())
    payload = {"client_id": "client", "iat": timestamp - 1000}
    token = jwt.encode(payload, "secret", algorithm="HS256")

    auth = JWTAuth(token)

    assert auth.payload == payload


@pytest.mark.django_db
@freeze_time("2021-08-23T14:20:00")
def test_exp_validated(settings):
    settings.JWT_EXPIRY = 3600
    JWTSecret.objects.create(identifier="client", secret="secret")
    timestamp = int(datetime.now().timestamp())
    payload = {"client_id": "client", "iat": timestamp - 3601}
    token = jwt.encode(payload, "secret", algorithm="HS256")

    auth = JWTAuth(token)

    with pytest.raises(PermissionDenied):
        auth.payload


@pytest.mark.django_db
@freeze_time("2021-08-23T14:20:00")
def test_exp_validated_with_leeway(settings):
    settings.JWT_EXPIRY = 3600
    settings.TIME_LEEWAY = 5
    JWTSecret.objects.create(identifier="client", secret="secret")
    timestamp = int(datetime.now().timestamp())
    payload = {"client_id": "client", "iat": timestamp - 3603}
    token = jwt.encode(payload, "secret", algorithm="HS256")

    auth = JWTAuth(token)

    assert auth.payload == payload


@pytest.mark.django_db
@freeze_time("2021-08-23T14:20:00")
def test_exp_validated_with_leeway_not_enough(settings):
    settings.JWT_EXPIRY = 3600
    settings.TIME_LEEWAY = 5
    JWTSecret.objects.create(identifier="client", secret="secret")
    timestamp = int(datetime.now().timestamp())
    payload = {"client_id": "client", "iat": timestamp - 3610}
    token = jwt.encode(payload, "secret", algorithm="HS256")

    auth = JWTAuth(token)

    with pytest.raises(PermissionDenied):
        auth.payload
