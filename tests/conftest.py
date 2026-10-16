"""
Define pytest configuration and setup.

The urls import is needed to make sure all urls/subclasses are registered
BEFORE fixtures run.
"""

import importlib
from collections.abc import Iterator

from django.urls import clear_script_prefix, set_script_prefix

import pytest
import structlog
from pytest_django import Settings
from pytest_factoryboy import register
from rest_framework.test import APIClient

from testapp import urls  # noqa
from testapp.factories import GroupFactory, HobbyFactory, PersonFactory

register(PersonFactory, "person")
register(HobbyFactory)
register(GroupFactory)


@pytest.fixture
def api_client():
    client = APIClient()
    return client


@pytest.fixture
def script_path(request):
    set_script_prefix("/some-prefix")
    request.addfinalizer(clear_script_prefix)


@pytest.fixture
def quiet_logs() -> Iterator[None]:
    """Keep the debug logs of ETag scheduling out of counterexamples."""
    config = structlog.get_config()
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger("info"))
    yield
    structlog.configure(**config)


@pytest.fixture
def etag_api(settings: Settings) -> None:
    """
    Route requests to the ETag tests' API, after its viewsets have registered their
    serializers: a write needs them to maintain the stored ETags.
    """
    importlib.import_module("testapp.etag_urls")
    settings.ROOT_URLCONF = "testapp.etag_urls"
