import os
from functools import lru_cache
from urllib.parse import urlparse

from django.conf import settings

import yaml
from requests_mock import Mocker

DEFAULT_PATH_PARAMETERS = {"version": "1"}

SPEC_PATH = os.path.join(settings.BASE_DIR, "src", "openapi.yaml")


@lru_cache()
def get_spec(path: str = SPEC_PATH) -> dict:
    with open(path, "r") as infile:
        spec = yaml.safe_load(infile)
    return spec


def get_operation_url(operation: str, spec_path: str = SPEC_PATH, **kwargs):
    """
    Look up the url of an operation from the API spec.
    """
    spec = get_spec(spec_path)
    url = spec["servers"][0]["url"]
    base_path = urlparse(url).path

    for path, methods in spec["paths"].items():
        for name, method in methods.items():
            if name == "parameters":
                continue

            if method["operationId"] == operation:
                format_kwargs = DEFAULT_PATH_PARAMETERS.copy()
                format_kwargs.update(**kwargs)
                path = path.format(**format_kwargs)
                return f"{base_path}{path}"

    raise ValueError(f"Operation {operation} not found")


class TypeCheckMixin:
    def assertResponseTypes(self, response_data: dict, types: tuple):
        """
        Do type checks on the response data.

        :param types: tuple of (field_name, class)
        :raises AssertionError: if the type mismatches
        """
        for field, type_ in types:
            with self.subTest(field=field, type=type_):
                self.assertIsInstance(response_data[field], type_)


def get_validation_errors(response, field, index=0):
    """
    Extra the validation error for ``field`` from the response.

    Assumes there's only one validation error for the field.
    """
    assert response.status_code == 400
    i = 0
    for error in response.data["invalid_params"]:
        if error["name"] != field:
            continue

        if i == index:
            return error

        i += 1


def mock_service_oas_get(
    mock: Mocker, url: str, service: str, oas_url: str = ""
) -> None:
    from zgw_consumers_oas.schema_loading import read_schema

    if not oas_url:
        oas_url = f"{url}schema/openapi.yaml?v=3"

    content = read_schema(service)
    mock.get(oas_url, content=content)
