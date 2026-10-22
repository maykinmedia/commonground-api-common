"""
Writes that lock the same rows in opposite orders deadlock: PostgreSQL detects it
and cancels one of them, whose request gets a 503.

Django creates foreign keys ``DEFERRABLE INITIALLY DEFERRED``, so a new or moved
row would lock its parent ``FOR KEY SHARE`` only at ``COMMIT``, after invalidating
the parent's stored ETag, where a save of the parent locks them the other way
round. So the save of a new or moved row locks the parent first.
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


def wait_for_a_lock_wait() -> None:
    """Wait until a transaction on the test database waits for a lock."""
    with connection.cursor() as cursor:
        for _ in range(1000):
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE datname = current_database() AND wait_event_type = 'Lock'"
            )
            if cursor.fetchone()[0]:
                return
            threading.Event().wait(0.01)
    raise AssertionError("no transaction waited for a lock")


@pytest.mark.parametrize("write", ["add", "move"])
def test_a_new_or_moved_child_does_not_deadlock_with_a_save_of_its_parent(
    write: str,
):
    """
    A sheet added to or moved into a folder, while another transaction saves the
    folder. Like a rol added to a zaak that is updated at the same time.
    """
    folder = Folder.objects.create(name="a", code="a")
    elsewhere = Folder.objects.create(name="b", code="b")
    sheet = Sheet.objects.create(folder=elsewhere, title="a", position=0)
    written, waiting = threading.Event(), threading.Event()

    def write_a_sheet() -> None:
        with transaction.atomic():
            if write == "add":
                Sheet.objects.create(folder=folder, title="b", position=1)
            else:
                sheet.folder = folder
                sheet.save(update_fields=["folder"])
            written.set()
            waiting.wait(timeout=10)

    def save_the_folder() -> None:
        written.wait(timeout=10)
        with transaction.atomic():
            renamed = Folder.objects.get(pk=folder.pk)
            renamed.name = "c"
            renamed.save()

    joins = [in_a_thread(write_a_sheet), in_a_thread(save_the_folder)]
    written.wait(timeout=10)
    wait_for_a_lock_wait()  # the save of the folder, for the sheet's transaction
    waiting.set()
    for join in joins:
        join()


@pytest.mark.parametrize("fields", [["code"], None], ids=["a shown column", "all"])
def test_two_children_that_save_their_parent(fields: list[str] | None):
    """
    Two sheets added to one folder at once, each saving the folder after, as Open
    Zaak's ``laatst_gemuteerd`` does. Locking the parent ``FOR KEY SHARE`` would
    let both in, and then neither could lock it for its save.
    """
    folder = Folder.objects.create(name="a", code="a")

    def add_and_save() -> None:
        with batched_invalidation(savepoint=False):
            Sheet.objects.create(folder=folder, title="a", position=0)
            threading.Event().wait(0.3)  # until the other one has added its sheet
            Folder.objects.get(pk=folder.pk).save(update_fields=fields)

    joins = [in_a_thread(add_and_save), in_a_thread(add_and_save)]
    for join in joins:
        join()


def test_a_batch_does_not_deadlock_with_a_write_to_the_parent():
    """
    Changing a child and then saving its parent, as Open Zaak's ``laatst_gemuteerd``
    does, against a save of the parent. Without the batch, the first locks the
    parent's stored ETag and then the parent, the second the other way round.
    """
    folder = Folder.objects.create(name="a", code="a")
    sheet = Sheet.objects.create(folder=folder, title="a", position=0)
    changed, locked = threading.Event(), threading.Event()

    def retitle_a_sheet() -> None:
        with batched_invalidation(savepoint=False):
            sheet.title = "b"
            sheet.save()
            changed.set()
            locked.wait(timeout=10)
            folder.save(update_fields=["name"])

    def rename_the_folder() -> None:
        changed.wait(timeout=10)
        with transaction.atomic():
            # as its save locks it, before it invalidates
            renamed = Folder.objects.select_for_update().get(pk=folder.pk)
            locked.set()
            renamed.name = "b"
            renamed.save()

    joins = [in_a_thread(retitle_a_sheet), in_a_thread(rename_the_folder)]
    for join in joins:
        join()
