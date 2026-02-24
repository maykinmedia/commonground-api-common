from django.test import override_settings

from rest_framework.exceptions import ValidationError

from vng_api_common.exception_handling import exception_handler


def _get_response(data):
    exc = ValidationError(data)
    return exception_handler(exc, context={})


def test_validation_errors_are_camelized_by_default():
    response = _get_response({"product_type_uuid": ["error"]})

    invalid_params = response.data["invalid_params"]
    assert invalid_params[0]["name"] == "productTypeUuid"


@override_settings(COMMONGROUND_API_COMMON={"API_EXCEPTION_CAMELIZE": False})
def test_validation_errors_can_be_snake_case():
    response = _get_response({"product_type_uuid": ["error"]})

    invalid_params = response.data["invalid_params"]
    assert invalid_params[0]["name"] == "product_type_uuid"
