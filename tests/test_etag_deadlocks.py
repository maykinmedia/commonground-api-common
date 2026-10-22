"""
Writes that lock the same rows in opposite orders deadlock, and Postgres aborts one
of them: its request fails with a 500.
"""

import threading
from collections.abc import Callable

from django.db import connection, transaction

import pytest

from testapp.models import Folder, Sheet
from vng_api_common.caching import batched_invalidation

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures("etag_api"),
]


def in_a_thread(work: Callable[[], None]) -> Callable[[], None]:
    """Start ``work`` on a connection of its own; the returned join raises its error."""
    errors: list[BaseException] = []

    def run() -> None:
        try:
            work()
        except BaseException as error:
            errors.append(error)
        finally:
            connection.close()

    thread = threading.Thread(target=run)
    thread.start()

    def join() -> None:
        thread.join(timeout=30)
        assert not thread.is_alive(), "the thread did not finish"
        if errors:
            raise errors[0]

    return join


def test_a_batch_does_not_deadlock_with_a_write_to_the_parent():
    """
    Adding a child and then saving its parent, as Open Zaak's ``laatst_gemuteerd``
    does, against a save of the parent. Without the batch, the first locks the
    parent's stored ETag and then the parent, the second the other way round.
    """
    folder = Folder.objects.create(name="a", code="a")
    added, locked = threading.Event(), threading.Event()

    def add_a_sheet() -> None:
        with batched_invalidation(savepoint=False):
            Sheet.objects.create(folder=folder, title="a", position=0)
            added.set()
            locked.wait(timeout=10)
            folder.save(update_fields=["name"])

    def rename_the_folder() -> None:
        added.wait(timeout=10)
        with transaction.atomic():
            # as its save locks it, before it invalidates
            renamed = Folder.objects.select_for_update().get(pk=folder.pk)
            locked.set()
            renamed.name = "b"
            renamed.save()

    joins = [in_a_thread(add_a_sheet), in_a_thread(rename_the_folder)]
    for join in joins:
        join()
