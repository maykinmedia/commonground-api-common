"""
What stored ETags cost, the reason for open-zaak#2577.

A write serializes nothing, and the number of SQL statements it sends doesn't
depend on how big the representations it affects are. A GET serializes no more
than it sends: a 304 nothing, a 200 with a stored ETag once.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from unittest.mock import patch

from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

import pytest

from testapp.models import Folder, Sheet, Tag
from testapp.serializers import SERIALIZERS

from .etags import detail_url

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures("etag_api"),
]

SMALL, LARGE = 1, 30


@dataclass(frozen=True)
class Seeded:
    folder: Folder  # with ``size`` sheets and tags
    other: Folder
    sheet: Sheet  # in ``folder``
    tag: Tag  # on no folder


def seed(size: int) -> Seeded:
    folder = Folder.objects.create(name="a", code="a")
    other = Folder.objects.create(name="b", code="b")
    for i in range(size):
        Sheet.objects.create(folder=folder, title=f"s{i}", position=i)
        Tag.objects.create(label=f"t{i}").folders.add(folder)
    sheet = folder.sheets.get(position=0)
    return Seeded(folder, other, sheet, Tag.objects.create(label="x"))


@dataclass(frozen=True)
class Cost:
    statements: int
    serializations: int


@contextmanager
def cost() -> Iterator[list[Cost]]:
    """Measure the block; the cost is in the yielded list once it ends."""
    patches = [
        patch.object(
            serializer,
            "to_representation",
            side_effect=serializer.to_representation,
            autospec=True,
        )
        for serializer in SERIALIZERS.values()
    ]
    measured: list[Cost] = []
    mocks = [p.start() for p in patches]
    try:
        with CaptureQueriesContext(connection) as statements:
            yield measured
    finally:
        for p in patches:
            p.stop()
    measured.append(Cost(len(statements), sum(mock.call_count for mock in mocks)))


def create_sheet(s: Seeded) -> None:
    Sheet.objects.create(folder=s.folder, title="new", position=-1)


def update_sheet(s: Seeded) -> None:
    s.sheet.title = "renamed"
    s.sheet.save()


def move_sheet(s: Seeded) -> None:
    s.sheet.folder = s.other
    s.sheet.save()


def delete_sheet(s: Seeded) -> None:
    s.sheet.delete()


def rename_folder(s: Seeded) -> None:
    s.folder.code = "c"  # shown by each of its sheets
    s.folder.save()


def tag_folder(s: Seeded) -> None:
    s.tag.folders.add(s.folder)


def untag_folder(s: Seeded) -> None:
    s.folder.tags.remove(s.folder.tags.get(label="t0"))


WRITES: tuple[Callable[[Seeded], None], ...] = (
    create_sheet,
    update_sheet,
    move_sheet,
    delete_sheet,
    rename_folder,
    tag_folder,
    untag_folder,
)


def write_cost(write: Callable[[Seeded], None], size: int) -> Cost:
    seeded = seed(size)
    client = Client()
    for folder in (seeded.folder, seeded.other):  # store the ETags a write affects
        client.get(detail_url(Folder, folder.pk))
    client.get(detail_url(Sheet, seeded.sheet.pk))
    with cost() as measured:
        write(seeded)
    return measured[0]


@pytest.mark.parametrize("write", WRITES)
def test_writes_do_not_serialize(write: Callable[[Seeded], None]):
    assert write_cost(write, LARGE).serializations == 0


@pytest.mark.parametrize("write", WRITES)
def test_a_write_costs_the_same_however_big_what_it_affects(
    write: Callable[[Seeded], None],
):
    assert write_cost(write, SMALL).statements == write_cost(write, LARGE).statements


def get_cost(size: int, conditional: bool) -> Cost:
    """The cost of a GET of a folder whose ETag is stored."""
    seeded = seed(size)
    client = Client()
    url = detail_url(Folder, seeded.folder.pk)
    etag = client.get(url)["ETag"]
    headers = {"If-None-Match": etag} if conditional else {}
    with cost() as measured:
        client.get(url, headers=headers)
    return measured[0]


def test_a_304_does_not_serialize():
    assert get_cost(LARGE, conditional=True).serializations == 0


def test_a_304_costs_the_same_however_big_the_resource():
    small = get_cost(SMALL, conditional=True)
    large = get_cost(LARGE, conditional=True)
    assert small.statements == large.statements


def test_a_200_with_a_stored_etag_serializes_once():
    assert get_cost(LARGE, conditional=False).serializations == 1
