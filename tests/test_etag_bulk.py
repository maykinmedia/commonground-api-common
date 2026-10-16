"""
``invalidating_update`` updates rows in bulk and invalidates what that affects,
as saves writing those fields would. The oracle runs it among other writes; these
are the cases it doesn't draw.
"""

from contextlib import nullcontext

from django.db import connection, transaction
from django.db.models import Count, F, Value
from django.db.models.functions import Concat
from django.test import Client

import pytest

from testapp.models import Folder, Sheet
from vng_api_common.caching import bulk, invalidating_update
from vng_api_common.caching.store import Resource

from .etags import ServedBodies, assert_served_etags_match

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures("etag_api"),
]


@pytest.fixture
def folders() -> tuple[Folder, Folder]:
    first, second = (Folder.objects.create(name=n, code=n) for n in "ab")
    for position in range(2):
        Sheet.objects.create(folder=first, title="a", position=position)
    return first, second


@pytest.mark.parametrize("atomic", [False, True], ids=["autocommit", "atomic"])
def test_a_move_in_bulk(client: Client, folders: tuple[Folder, Folder], atomic: bool):
    first, second = folders
    served = ServedBodies()
    assert_served_etags_match(client, served)

    with transaction.atomic() if atomic else nullcontext():
        count = invalidating_update(Sheet.objects.filter(folder=first), folder=second)

    assert count == 2
    assert_served_etags_match(client, served)


def test_an_expression_of_an_annotated_queryset(
    client: Client, folders: tuple[Folder, Folder]
):
    served = ServedBodies()
    assert_served_etags_match(client, served)
    sheets = Sheet.objects.annotate(code=F("folder__code")).filter(code="a")

    invalidating_update(sheets, title=Concat(F("title"), Value("!")))

    assert set(Sheet.objects.values_list("title", flat=True)) == {"a!"}
    assert_served_etags_match(client, served)


def test_nothing_to_update(folders: tuple[Folder, Folder]):
    assert invalidating_update(Sheet.objects.none(), title="b") == 0


@pytest.mark.parametrize("selecting", ["distinct", "aggregate"])
def test_a_queryset_that_cant_be_locked_as_it_is(
    client: Client, folders: tuple[Folder, Folder], selecting: str
):
    served = ServedBodies()
    assert_served_etags_match(client, served)
    sheets = (
        Sheet.objects.filter(folder__code="a").distinct()
        if selecting == "distinct"
        else Sheet.objects.annotate(n=Count("folder__sheets")).filter(n__gt=0)
    )

    assert invalidating_update(sheets, title="b") == 2
    assert_served_etags_match(client, served)


class Interrupted(Exception):
    """As a worker's timeout would, between the update and invalidating."""


@pytest.mark.parametrize("mode", ["manual", "atomic"])
def test_a_failure_after_the_update(
    client: Client,
    folders: tuple[Folder, Folder],
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
):
    second = folders[1]
    served = ServedBodies()
    assert_served_etags_match(client, served)
    invalidate = bulk.invalidate
    calls: list[object] = []

    def interrupted(resources: frozenset[Resource]) -> None:
        calls.append(resources)
        if len(calls) == 2:  # after the update
            raise Interrupted
        invalidate(resources)

    monkeypatch.setattr(bulk, "invalidate", interrupted)
    if mode == "manual":  # a transaction managed by hand: no atomic block
        transaction.set_autocommit(False)
        try:
            with pytest.raises(Interrupted):
                invalidating_update(Sheet.objects.all(), folder=second)
            connection.commit()
        finally:
            transaction.set_autocommit(True)
    else:  # caught, inside an atomic block, which then can only roll back
        with (
            pytest.raises(transaction.TransactionManagementError),
            transaction.atomic(),
        ):
            with pytest.raises(Interrupted):
                invalidating_update(Sheet.objects.all(), folder=second)
            Folder.objects.count()
    monkeypatch.undo()

    assert_served_etags_match(client, served)


def test_the_recipe_of_main_after_a_queryset_update(
    client: Client, folders: tuple[Folder, Folder]
):
    """``main`` documented calculating the ETag after a ``QuerySet.update``."""
    first, _ = folders
    served = ServedBodies()
    assert_served_etags_match(client, served)

    Folder.objects.filter(pk=first.pk).update(name="c")
    first.refresh_from_db()
    with pytest.deprecated_call():
        first.calculate_etag_value()

    assert_served_etags_match(client, served)
