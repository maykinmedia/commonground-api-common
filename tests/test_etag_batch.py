"""
``batched_invalidation`` writes the tokens of the writes in it in one statement at
its end. The oracle and the concurrency machine run writes in batches among other
writes; these are what they don't count.
"""

from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext

import pytest

from testapp.models import Folder, Sheet
from vng_api_common.caching import batched_invalidation
from vng_api_common.caching.models import StoredETag

from .etags import ServedBodies, assert_served_etags_match

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures("etag_api"),
]

TABLE = StoredETag._meta.db_table


class Rollback(Exception):
    """Rolls back the block it is raised in."""


@pytest.fixture
def folder() -> Folder:
    return Folder.objects.create(name="a", code="a")


def token_writes(statements: CaptureQueriesContext) -> list[str]:
    return [
        q["sql"] for q in statements if q["sql"].startswith(f'INSERT INTO "{TABLE}"')
    ]


def add_sheets(folder: Folder) -> None:
    for position in range(3):
        Sheet.objects.create(folder=folder, title="a", position=position)


def test_a_batch_writes_its_tokens_in_one_statement(client: Client, folder: Folder):
    served = ServedBodies()
    assert_served_etags_match(client, served)

    with CaptureQueriesContext(connection) as statements, batched_invalidation():
        add_sheets(folder)

    assert len(token_writes(statements)) == 1
    assert_served_etags_match(client, served)


def test_a_nested_batch_leaves_writing_to_the_outer_one(folder: Folder):
    with CaptureQueriesContext(connection) as statements, batched_invalidation():
        with batched_invalidation():
            add_sheets(folder)
        assert token_writes(statements) == []
        Sheet.objects.create(folder=folder, title="b", position=3)

    assert len(token_writes(statements)) == 1


def test_a_batch_rolled_back_writes_nothing(client: Client, folder: Folder):
    served = ServedBodies()
    assert_served_etags_match(client, served)

    with CaptureQueriesContext(connection) as statements:
        with pytest.raises(Rollback), batched_invalidation():
            add_sheets(folder)
            raise Rollback

    assert token_writes(statements) == []
    assert not folder.sheets.exists()
    assert_served_etags_match(client, served)


def test_a_savepoint_rolled_back_in_a_batch_still_invalidates(
    client: Client, folder: Folder
):
    served = ServedBodies()
    assert_served_etags_match(client, served)

    with batched_invalidation():
        with pytest.raises(Rollback), transaction.atomic():
            add_sheets(folder)
            raise Rollback

    assert not folder.sheets.exists()
    assert_served_etags_match(client, served)


def test_a_resource_deleted_in_a_batch_keeps_no_stored_etag(folder: Folder):
    with batched_invalidation():
        sheet = Sheet.objects.create(folder=folder, title="a", position=0)
        pk = sheet.pk
        sheet.delete()

    assert not StoredETag.objects.filter(model="testapp.sheet", object_id=str(pk))


def test_a_delete_rolled_back_in_a_batch_keeps_the_invalidation(
    client: Client, folder: Folder
):
    """The oracle found it: the rollback undid the delete, but not its forgetting."""
    served = ServedBodies()
    assert_served_etags_match(client, served)

    with batched_invalidation():
        Sheet.objects.create(folder=folder, title="a", position=0)
        with pytest.raises(Rollback), transaction.atomic():
            folder.delete()
            raise Rollback

    assert_served_etags_match(client, served)


def test_a_batch_without_a_savepoint(client: Client, folder: Folder):
    served = ServedBodies()
    assert_served_etags_match(client, served)

    with CaptureQueriesContext(connection) as statements, transaction.atomic():
        with batched_invalidation(savepoint=False):
            add_sheets(folder)

    assert not [q for q in statements if q["sql"].startswith("SAVEPOINT")]
    assert len(token_writes(statements)) == 1
    assert_served_etags_match(client, served)
