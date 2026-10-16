"""
What registering a viewset's serializer records: the relations it reads, with
the columns of the rows they reach that link them and that it shows. A nested
serializer is followed through relations, and through a group of its row's
columns; a nested serializer or related field it can't follow is warned about.
"""

from collections.abc import Iterator, MutableMapping
from unittest.mock import patch

from django.db.models import Model

import pytest
from rest_framework import serializers, viewsets
from rest_framework.fields import Field
from structlog.testing import capture_logs

from testapp.models import Folder, Person, Sheet, Shortcut
from testapp.serializers import AddressSerializer, SheetSerializer
from vng_api_common.caching.registry import ALL, Dependency, extract_dependencies
from vng_api_common.serializers import CachedHyperlinkedRelatedField


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


class FolderUrl(serializers.HyperlinkedRelatedField):
    def get_url(self, obj, view_name, request, format):  # may read any column
        return super().get_url(obj, view_name, request, format)


class FolderInFull(serializers.ModelSerializer):
    class Meta:
        model = Folder
        fields = ("name",)


def showing(field: Field) -> type[serializers.Serializer]:
    """A serializer of sheets showing their folder with ``field``."""
    meta = type("Meta", (), {"model": Sheet, "fields": ("shown",)})
    return type(
        "SheetShowing", (serializers.ModelSerializer,), {"shown": field, "Meta": meta}
    )


@pytest.mark.parametrize(
    ("field", "shown"),
    [
        (
            CachedHyperlinkedRelatedField(
                source="folder", view_name="folder-detail", read_only=True
            ),
            frozenset(),
        ),
        (
            serializers.HyperlinkedRelatedField(
                source="folder",
                view_name="folder-detail",
                lookup_field="code",
                read_only=True,
            ),
            frozenset({"code"}),
        ),
        (
            serializers.SlugRelatedField(
                source="folder", slug_field="code", read_only=True
            ),
            frozenset({"code"}),
        ),
        (
            serializers.PrimaryKeyRelatedField(source="folder", read_only=True),
            frozenset(),
        ),
        (serializers.CharField(source="folder.name"), frozenset({"name"})),
        (serializers.StringRelatedField(source="folder"), ALL),
        (FolderUrl(source="folder", view_name="folder-detail", read_only=True), ALL),
        (FolderInFull(source="folder"), ALL),
    ],
    ids=[
        "hyperlink",
        "hyperlink by code",
        "slug",
        "pk",
        "column",
        "str",
        "own URL",
        "nested",
    ],
)
def test_what_a_field_shows_of_the_row_it_reaches(registry, field, shown):
    register(Sheet, showing(field))

    assert registry[Folder] == {Dependency(Sheet, "folder", frozenset(), shown)}


def test_a_reverse_foreign_key_links_by_the_rows_it_reaches(registry):
    sheets = CachedHyperlinkedRelatedField(
        view_name="sheet-detail", many=True, read_only=True
    )
    meta = type("Meta", (), {"model": Folder, "fields": ("sheets",)})
    register(
        Folder,
        type(
            "FolderSheets",
            (serializers.ModelSerializer,),
            {"sheets": sheets, "Meta": meta},
        ),
    )

    assert registry[Sheet] == {
        Dependency(
            Folder,
            "sheets",
            frozenset({"folder"}),
            frozenset({"position"}),
            "folder_id",
        )
    }


def test_a_related_field_through_a_property_is_warned_about(registry):
    latest = CachedHyperlinkedRelatedField(
        source="latest_sheet", view_name="sheet-detail", read_only=True
    )
    meta = type("Meta", (), {"model": Folder, "fields": ("latest",)})
    serializer = type(
        "FolderLatest", (serializers.ModelSerializer,), {"latest": latest, "Meta": meta}
    )

    assert register(Folder, serializer) == ["related_source_not_a_relation"]
    assert registry == {}


@pytest.mark.parametrize(
    ("source", "model", "ordering"),
    [("sheets", Sheet, {"position"}), ("shortcuts", Shortcut, {"label"})],
)
def test_a_list_shows_the_columns_that_order_it(registry, source, model, ordering):
    listed = CachedHyperlinkedRelatedField(
        source=source, view_name="sheet-detail", many=True, read_only=True
    )
    meta = type("Meta", (), {"model": Folder, "fields": ("listed",)})
    attrs = {"listed": listed, "Meta": meta}
    register(Folder, type("FolderListing", (serializers.ModelSerializer,), attrs))

    (dependency,) = registry[model]
    assert dependency.shown == ordering
