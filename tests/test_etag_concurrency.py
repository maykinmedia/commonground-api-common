"""
Concurrent writers and readers: whatever the interleaving, once no transaction is
open, every resource serves the ETag of its current representation, and at no
time is an ETag served with two bodies.

A hypothesis state machine drives three worker threads, each with a database
connection of its own, one step at a time: begin a transaction, write, commit or
roll back, or GET a resource. Between transactions the data may come to predate
stored ETags, as right after the upgrade. Any step may pause its worker right after COMMIT,
or before or after the reads of a folder's serialization (see
``testapp.checkpoints``), wherever that happens: in a callback after commit, while
answering a GET, or elsewhere. The
other workers then run until the machine resumes it. After every step the
machine waits until each worker is idle, paused, or waiting on a Postgres lock,
so a worker blocked by a paused one does not stall it. Workers in a deadlock are
waited for until Postgres aborts one of their transactions, about a second.
Every step is one a worker can take: hypothesis draws the worker from those.

This reproduces, for instance, the lost update of recomputing after commit: a
recompute pauses after reading a folder's sheets, another worker adds a sheet
and commits, and the paused recompute then stores its stale ETag last. And the
window it leaves: while the recompute is paused, a GET serves the new body under
the old ETag.

Set ``ETAG_CONCURRENCY_EXAMPLES`` to run more examples than the default. Run
pytest with ``--hypothesis-show-statistics`` to see how often transactions abort,
and why.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from collections.abc import Callable, Collection, Mapping
from enum import Enum

from django.db import DatabaseError, connection, transaction
from django.db.models import Model
from django.test import Client

import pytest
from hypothesis import (
    HealthCheck,
    Phase,
    currently_in_test_context,
    event,
    settings,
    strategies as st,
)
from hypothesis.stateful import (
    RuleBasedStateMachine,
    get_state_machine_test,
    invariant,
    precondition,
    rule,
)

from testapp import checkpoints
from testapp.models import Folder, Sheet, Tag

from .etags import (
    RESOURCES,
    ServedBodies,
    assert_served_etags_match,
    detail_url,
    forget_stored_etags,
    reset_database,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures("etag_api", "quiet_logs"),
]

SETTLE_TIMEOUT = 30  # seconds the workers get to become idle, paused or blocked


class Abort(Enum):
    """
    Why a worker's transaction can only roll back, by SQLSTATE. The violations are
    of writing rows another transaction changed meanwhile.
    """

    DEADLOCK = "40P01"
    SERIALIZATION_FAILURE = "40001"
    LOCK_NOT_AVAILABLE = "55P03"
    FOREIGN_KEY_VIOLATION = "23503"
    UNIQUE_VIOLATION = "23505"


type Step = Callable[[], None]
type Write = Callable[[int, int, str], None]


def abort_of(error: DatabaseError) -> Abort | None:
    cause = error.__cause__
    code: object = getattr(cause, "pgcode", None) or getattr(cause, "sqlstate", None)
    try:
        return Abort(code)
    except ValueError:
        return None


class Rollback(Exception):
    """Rolls back the transaction it is raised in."""


class Worker:
    """A thread with a database connection of its own, run one step at a time."""

    def __init__(self, name: str, served: ServedBodies) -> None:
        self.served = served
        self.steps: queue.Queue[Step | None] = queue.Queue()
        self.done = threading.Event()
        self.done.set()
        self.error: BaseException | None = None
        self.gate: checkpoints.Gate | None = None
        self.atomic: transaction.Atomic | None = None
        self.committed = False
        self.aborts: list[Abort] = []  # of its transactions, since the machine looked
        self.client = Client()
        self.thread = threading.Thread(target=self._serve, name=name, daemon=True)
        self.thread.start()
        self.pid = 0
        self.submit(self._connect, pause_at=None)
        self.done.wait()

    def _serve(self) -> None:
        while (step := self.steps.get()) is not None:
            try:
                step()
            except BaseException as error:
                self.error = error
            finally:
                self.done.set()
        connection.close()

    @property
    def thread_id(self) -> int:
        assert self.thread.ident is not None
        return self.thread.ident

    @property
    def idle(self) -> bool:
        return self.done.is_set()

    @property
    def in_transaction(self) -> bool:
        return self.atomic is not None

    @property
    def paused(self) -> bool:
        return (
            self.gate is not None
            and self.gate.reached.is_set()
            and not self.gate.opened.is_set()
        )

    def submit(self, step: Step, *, pause_at: int | None) -> None:
        """Run ``step``, pausing at checkpoint ``pause_at`` (counting from 0), if any."""
        self.gate = (
            None if pause_at is None else checkpoints.arm(self.thread_id, pause_at)
        )
        self.done.clear()
        self.steps.put(step)

    def resume(self) -> None:
        assert self.gate is not None
        self.gate.opened.set()

    def forget_unreached_gate(self) -> None:
        if self.gate is not None and not self.gate.reached.is_set():
            checkpoints.disarm(self.thread_id)
            self.gate = None

    def stop(self) -> None:
        if self.gate is not None:
            self.gate.opened.set()
        self.steps.put(None)
        self.thread.join(timeout=SETTLE_TIMEOUT)

    # steps, run in the worker's thread

    def _connect(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            (self.pid,) = cursor.fetchone()

    def begin(self) -> None:
        self.atomic = transaction.atomic()
        self.atomic.__enter__()
        self.committed = False
        transaction.on_commit(self._mark_committed)

    def _mark_committed(self) -> None:
        # registered first, so it runs right after COMMIT, before any callback the
        # ETag code registers: a step may pause in between
        self.committed = True
        checkpoints.checkpoint()

    def write(self, write: Write, rank: int, other: int, value: str) -> None:
        try:
            write(rank, other, value)
        except DatabaseError as error:
            if (abort := abort_of(error)) is None:
                raise
            self.aborts.append(abort)
            self._close(error)

    def commit(self) -> None:
        try:
            self._close(None)
        except DatabaseError as error:
            # an error after the commit is the ETag code's, not a lost race
            if self.committed or (abort := abort_of(error)) is None:
                raise
            self.aborts.append(abort)

    def rollback(self) -> None:
        self._close(Rollback())

    def _close(self, error: BaseException | None) -> None:
        atomic, self.atomic = self.atomic, None
        assert atomic is not None
        if error is None:
            atomic.__exit__(None, None, None)
        else:
            atomic.__exit__(type(error), error, error.__traceback__)

    def get(self, model: type[Model], rank: int) -> None:
        if instance := nth(model, rank):
            path = detail_url(model, instance.pk)
            response = self.client.get(path)
            # 404: another worker deleted it meanwhile
            assert response.status_code in [200, 404], response.status_code
            if response.status_code == 200:
                self.served.record(path, response.get("ETag"), response.content)


def nth[M: Model](model: type[M], rank: int) -> M | None:
    rows = list(model._default_manager.order_by("pk"))
    return rows[rank % len(rows)] if rows else None


def add_sheet(rank: int, other: int, value: str) -> None:
    if folder := nth(Folder, rank):
        Sheet.objects.create(folder=folder, title=value, position=other % 2)


def delete_sheet(rank: int, other: int, value: str) -> None:
    if sheet := nth(Sheet, rank):
        sheet.delete()


def move_sheet(rank: int, other: int, value: str) -> None:
    if (sheet := nth(Sheet, rank)) and (folder := nth(Folder, other)):
        sheet.folder = folder
        sheet.save()


def retitle_sheet(rank: int, other: int, value: str) -> None:
    if sheet := nth(Sheet, rank):
        sheet.title = value
        sheet.save()


def rename_folder(rank: int, other: int, value: str) -> None:
    if folder := nth(Folder, rank):
        folder.name = value
        folder.save()


def tag_folder(rank: int, other: int, value: str) -> None:
    if (tag := nth(Tag, rank)) and (folder := nth(Folder, other)):
        tag.folders.add(folder)


def untag_folder(rank: int, other: int, value: str) -> None:
    if (tag := nth(Tag, rank)) and (folder := nth(Folder, other)):
        folder.tags.remove(tag)


WRITES: tuple[Write, ...] = (
    add_sheet,
    delete_sheet,
    move_sheet,
    retitle_sheet,
    rename_folder,
    tag_folder,
    untag_folder,
)

WORKERS = 3
RANK = st.integers(min_value=0, max_value=2)
VALUES = st.sampled_from(["a", "b"])
# the checkpoints a step may pause at: right after COMMIT, and before and after
# the reads of the folders it serializes
CHECKPOINTS = range(4)
PAUSE_AT = st.none() | st.sampled_from(CHECKPOINTS)


def outside_transaction(worker: Worker) -> bool:
    """Whether the worker can begin a transaction or GET."""
    return worker.idle and not worker.in_transaction


def inside_transaction(worker: Worker) -> bool:
    """Whether the worker can write in its transaction, commit or roll back."""
    return worker.idle and worker.in_transaction


def quiet(machine: ConcurrentEtags) -> bool:
    """Whether no worker is busy or in a transaction, as during a migration."""
    return all(map(outside_transaction, machine.workers))


def paused(worker: Worker) -> bool:
    """Whether the worker can resume."""
    return worker.paused


def workers_that(can: Callable[[Worker], bool]) -> st.SearchStrategy[int]:
    """A worker for which ``can`` holds, drawn when the step is: none is wasted."""

    def eligible(machine: ConcurrentEtags) -> st.SearchStrategy[int]:
        return st.sampled_from(
            [w for w, worker in enumerate(machine.workers) if can(worker)]
        )

    return st.runner().flatmap(eligible)


def any_worker(can: Callable[[Worker], bool]) -> Callable[[ConcurrentEtags], bool]:
    """A precondition: ``can`` holds for a worker of the machine."""
    return lambda machine: any(map(can, machine.workers))


def lock_waits(pids: Collection[int]) -> dict[int, list[int]]:
    """The backends of ``pids`` that wait on a lock, with the backends they wait on."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pid, pg_blocking_pids(pid) FROM pg_stat_activity"
            " WHERE pid = ANY(%s) AND wait_event_type = 'Lock'",
            [list(pids)],
        )
        return dict(cursor.fetchall())


def deadlocked(waits: Mapping[int, Collection[int]]) -> bool:
    """Whether backends wait on each other in a cycle."""
    for start in waits:
        seen: set[int] = set()
        todo = list(waits[start])
        while todo:
            if (pid := todo.pop()) == start:
                return True
            if pid not in seen:
                seen.add(pid)
                todo.extend(waits.get(pid, []))
    return False


def tally(abort: Abort) -> None:
    """Count an abort in the statistics: ``pytest --hypothesis-show-statistics``."""
    if currently_in_test_context():  # not in the interleavings written out below
        event(f"abort: {abort.name}")


class ConcurrentEtags(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        reset_database()
        first, second = (Folder.objects.create(name="a", code="a") for _ in range(2))
        Sheet.objects.create(folder=first, title="a", position=0)
        Tag.objects.create(label="a").folders.add(second)
        self.client = Client()
        self.served = ServedBodies()
        self.workers = [Worker(f"worker {i}", self.served) for i in range(WORKERS)]

    def settle(self) -> None:
        """
        Wait until every worker is idle, paused, or waiting on a lock that another
        step can release. Workers in a deadlock are waited for: Postgres aborts one
        of their transactions after ``deadlock_timeout``.
        """
        deadline = time.monotonic() + SETTLE_TIMEOUT
        while True:
            busy = [w for w in self.workers if not w.idle and not w.paused]
            waits = lock_waits([w.pid for w in self.workers])
            if all(w.pid in waits for w in busy) and not deadlocked(waits):
                break
            if time.monotonic() > deadline:
                raise RuntimeError("The workers did not settle")
            time.sleep(0.005)
        for worker in self.workers:
            if worker.idle:
                worker.forget_unreached_gate()
                for abort in worker.aborts:
                    tally(abort)
                worker.aborts.clear()
            if worker.error is not None:
                error, worker.error = worker.error, None
                raise error

    def step(self, worker: Worker, step: Step, *, pause_at: int | None = None) -> None:
        worker.submit(step, pause_at=pause_at)
        self.settle()

    # Each rule checks its worker can take the step, also when called directly.

    @precondition(any_worker(outside_transaction))
    @rule(w=workers_that(outside_transaction))
    def begin(self, w: int) -> None:
        worker = self.workers[w]
        if outside_transaction(worker):
            self.step(worker, worker.begin)

    @precondition(any_worker(inside_transaction))
    @rule(
        w=workers_that(inside_transaction),
        write=st.sampled_from(WRITES),
        rank=RANK,
        other=RANK,
        value=VALUES,
        pause_at=PAUSE_AT,
    )
    def write(
        self,
        w: int,
        write: Write,
        rank: int,
        other: int,
        value: str,
        pause_at: int | None,
    ) -> None:
        worker = self.workers[w]
        if inside_transaction(worker):
            self.step(
                worker,
                lambda: worker.write(write, rank, other, value),
                pause_at=pause_at,
            )

    @precondition(any_worker(inside_transaction))
    @rule(w=workers_that(inside_transaction), pause_at=PAUSE_AT)
    def commit(self, w: int, pause_at: int | None) -> None:
        worker = self.workers[w]
        if inside_transaction(worker):
            self.step(worker, worker.commit, pause_at=pause_at)

    @precondition(any_worker(inside_transaction))
    @rule(w=workers_that(inside_transaction))
    def rollback(self, w: int) -> None:
        worker = self.workers[w]
        if inside_transaction(worker):
            self.step(worker, worker.rollback)

    @precondition(any_worker(outside_transaction))
    @rule(
        w=workers_that(outside_transaction),
        model=st.sampled_from(list(RESOURCES)),
        rank=RANK,
        pause_at=PAUSE_AT,
    )
    def get(self, w: int, model: type[Model], rank: int, pause_at: int | None) -> None:
        worker = self.workers[w]
        if outside_transaction(worker):
            self.step(worker, lambda: worker.get(model, rank), pause_at=pause_at)

    @precondition(quiet)
    @rule()
    def upgrade(self) -> None:
        if quiet(self):
            forget_stored_etags()

    @precondition(any_worker(paused))
    @rule(w=workers_that(paused))
    def resume(self, w: int) -> None:
        worker = self.workers[w]
        if paused(worker):
            worker.resume()
            self.settle()

    @invariant()
    def served_etags_match_representations(self) -> None:
        if all(map(outside_transaction, self.workers)):
            assert_served_etags_match(self.client, self.served)

    def teardown(self) -> None:
        try:
            self.drain()
            assert_served_etags_match(self.client, self.served)
        finally:
            for worker in self.workers:
                worker.stop()

    def drain(self) -> None:
        """Resume every paused worker and commit every open transaction."""
        for _ in range(10 * WORKERS):
            for worker in self.workers:
                if worker.paused:
                    worker.resume()
            self.settle()
            if all(map(outside_transaction, self.workers)):
                return
            for worker in self.workers:
                if inside_transaction(worker):
                    self.step(worker, worker.commit)
        raise RuntimeError("The workers did not drain")


# The state machine's own hypothesis test, rather than a test that calls
# run_state_machine_as_test, so --hypothesis-show-statistics reports on it. Its
# fixtures hold for every example: the machine resets the database itself.
test_concurrent_writes_leave_served_etags_matching = get_state_machine_test(
    ConcurrentEtags,
    settings=settings(
        max_examples=int(os.getenv("ETAG_CONCURRENCY_EXAMPLES", "100")),
        stateful_step_count=15,
        deadline=None,
        phases=[Phase.explicit, Phase.reuse, Phase.generate, Phase.shrink],
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.function_scoped_fixture,
        ],
    ),
)


# The interleavings below are written out, so they run whatever the odds of
# hypothesis finding them. Each pauses at every checkpoint in turn: where a step
# serializes a folder depends on how ETags are maintained.


@pytest.mark.parametrize("pause_at", CHECKPOINTS)
def test_lost_update_of_a_recompute_after_commit(pause_at: int) -> None:
    """
    A worker commits a new sheet and its folder's recompute pauses after reading
    the sheets. Another worker adds a sheet and commits. The paused recompute then
    resumes. In designs whose commits serialize nothing, the pause never happens.
    """
    machine = ConcurrentEtags()
    try:
        machine.begin(w=0)
        machine.write(w=0, write=add_sheet, rank=0, other=0, value="a", pause_at=None)
        machine.commit(w=0, pause_at=pause_at)
        machine.begin(w=1)
        machine.write(w=1, write=add_sheet, rank=0, other=0, value="b", pause_at=None)
        machine.commit(w=1, pause_at=None)
        machine.resume(w=0)
    finally:
        machine.teardown()


@pytest.mark.parametrize("pause_at", CHECKPOINTS)
def test_a_get_while_a_commit_is_paused(pause_at: int) -> None:
    """
    A folder is served. A worker commits a new sheet in it and pauses, like a
    recompute after commit. Meanwhile another worker GETs the folder: it sees the
    new sheet, so it must not see the old ETag.
    """
    machine = ConcurrentEtags()
    try:
        machine.served_etags_match_representations()
        machine.begin(w=0)
        machine.write(w=0, write=add_sheet, rank=0, other=0, value="b", pause_at=None)
        machine.commit(w=0, pause_at=pause_at)
        machine.get(w=1, model=Folder, rank=0, pause_at=None)
        machine.resume(w=0)
    finally:
        machine.teardown()


@pytest.mark.parametrize("pause_at", CHECKPOINTS)
def test_a_commit_while_a_get_is_paused(pause_at: int) -> None:
    """
    A folder is served. A worker GETs it again and pauses, between reading a stored
    ETag and the body, or between computing the ETag and serializing the body.
    Meanwhile another worker commits a new sheet in it. The paused GET must still
    serve an ETag and a body that belong together.
    """
    machine = ConcurrentEtags()
    try:
        machine.served_etags_match_representations()
        machine.get(w=1, model=Folder, rank=0, pause_at=pause_at)
        machine.begin(w=0)
        machine.write(w=0, write=add_sheet, rank=0, other=0, value="b", pause_at=None)
        machine.commit(w=0, pause_at=None)
        machine.resume(w=1)
    finally:
        machine.teardown()


@pytest.mark.parametrize("pause_at", CHECKPOINTS)
def test_a_get_filling_in_while_a_commit_lands(pause_at: int) -> None:
    """
    A commit leaves a folder's ETag to be filled in. A worker GETs the folder and
    pauses, while it calculates the ETag or after. Meanwhile another worker commits
    a new sheet in the folder. The paused GET may serve what it read, but must not
    store its ETag over the newer write.
    """
    machine = ConcurrentEtags()
    try:
        machine.served_etags_match_representations()
        machine.begin(w=0)
        machine.write(w=0, write=add_sheet, rank=0, other=0, value="a", pause_at=None)
        machine.commit(w=0, pause_at=None)
        machine.get(w=1, model=Folder, rank=0, pause_at=pause_at)
        machine.begin(w=0)
        machine.write(w=0, write=add_sheet, rank=0, other=0, value="b", pause_at=None)
        machine.commit(w=0, pause_at=None)
        machine.resume(w=1)
    finally:
        machine.teardown()


@pytest.mark.parametrize("pause_at", CHECKPOINTS)
def test_a_first_fill_while_a_commit_lands(pause_at: int) -> None:
    """
    Right after the upgrade, a worker GETs a folder, the first to since, and pauses
    while it calculates the ETag. Meanwhile another worker commits a new sheet in
    the folder. The paused GET must not store its ETag over the newer write.
    """
    machine = ConcurrentEtags()
    try:
        machine.upgrade()
        machine.get(w=1, model=Folder, rank=0, pause_at=pause_at)
        machine.begin(w=0)
        machine.write(w=0, write=add_sheet, rank=0, other=0, value="b", pause_at=None)
        machine.commit(w=0, pause_at=None)
        machine.resume(w=1)
    finally:
        machine.teardown()


def test_a_first_fill_while_a_write_is_open() -> None:
    """
    Right after the upgrade, a worker adds a sheet to a folder and keeps its
    transaction open. Another worker GETs the folder, the first to since: it reads
    the folder without the sheet. Then the writer commits. The GET must not store
    its ETag over the write.
    """
    machine = ConcurrentEtags()
    try:
        machine.upgrade()
        machine.begin(w=0)
        machine.write(w=0, write=add_sheet, rank=0, other=0, value="b", pause_at=None)
        machine.get(w=1, model=Folder, rank=0, pause_at=None)
        machine.commit(w=0, pause_at=None)
    finally:
        machine.teardown()


def test_moves_of_one_sheet_by_two_transactions() -> None:
    """
    A worker moves a sheet to the second folder. Another worker moves it back, and
    waits for the first to commit. The second must invalidate the folder the sheet
    is in by then, not the one it read before it waited. A GET fills that folder's
    ETag in before the second commits.
    """
    machine = ConcurrentEtags()
    try:
        machine.served_etags_match_representations()
        machine.begin(w=0)
        machine.write(w=0, write=move_sheet, rank=0, other=1, value="a", pause_at=None)
        machine.begin(w=1)
        machine.write(w=1, write=move_sheet, rank=0, other=0, value="a", pause_at=None)
        machine.commit(w=0, pause_at=None)
        machine.get(w=2, model=Folder, rank=1, pause_at=None)
        machine.commit(w=1, pause_at=None)
    finally:
        machine.teardown()
