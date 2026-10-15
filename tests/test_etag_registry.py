"""
What registering a viewset's serializer records: a nested serializer is followed
through relations, and through a group of its row's columns; one it can't follow
is warned about.
"""

from collections.abc import Iterator, MutableMapping
from unittest.mock import patch

from django.db.models import Model

import pytest
from rest_framework import serializers, viewsets
from structlog.testing import capture_logs

from testapp.models import Folder, Person
from testapp.serializers import AddressSerializer, SheetSerializer
from vng_api_common.caching.registry import extract_dependencies


class PersonWithAddress(serializers.ModelSerializer):
    address = AddressSerializer(allow_null=True)  # a group of the person's columns

    class Meta:
        model = Person
        fields = ("address",)


class FolderWithLatestSheet(serializers.ModelSerializer):
    latest_sheet = SheetSerializer(read_only=True)  # a property, say

    class Meta:
        model = Folder
        fields = ("latest_sheet",)


@pytest.fixture
def registry() -> Iterator[MutableMapping[type[Model], object]]:
    """Empty registries to register into; the dependencies are yielded."""
    with (
        patch("vng_api_common.caching.registry.DEPENDENCY_REGISTRY", new={}) as deps,
        patch("vng_api_common.caching.registry.MODEL_SERIALIZERS", new={}),
    ):
        yield deps


def register(model: type[Model], serializer: type[serializers.Serializer]) -> list[str]:
    """Register a viewset of ``model`` with ``serializer``; the events it logs."""
    viewset = type(
        "ViewSet",
        (viewsets.ReadOnlyModelViewSet,),
        {"queryset": model._default_manager.all(), "serializer_class": serializer},
    )
    with capture_logs() as logs:
        extract_dependencies(viewset, frozenset())
    return [log["event"] for log in logs]


def test_a_group_of_columns_reads_its_own_row(registry):
    assert register(Person, PersonWithAddress) == []
    assert registry == {}


def test_a_nested_serializer_through_a_property_is_warned_about(registry):
    assert register(Folder, FolderWithLatestSheet) == ["nested_source_not_a_relation"]
    assert registry == {}
