"""
Oracle for stored ETags: whatever the writes, a GET serves the ETag of the
resource's current representation.

A hypothesis state machine writes through the ORM, the way application code
does: in transactions, with savepoints that are kept or rolled back, through
several Python objects for one row, with and without ``update_fields``, on both
sides of a many-to-many, with deletes that cascade or set null. A transaction may
start from data that predates stored ETags, as right after the upgrade. After every
transaction it sends each resource a GET conditional on the ETag of its current
representation, as computed by ``calculate_etag`` for a freshly loaded object,
and expects a 304 carrying that ETag, for a HEAD too.

It only relies on public behaviour, so it holds for any way of maintaining the
stored ETags. The models and their representations are in ``testapp``: see
``Folder``, ``Sheet``, ``Tag``, ``Attachment`` and ``Shortcut``.

Set ``ETAG_ORACLE_EXAMPLES`` to run more examples than the default.
"""

import os
from collections.abc import Callable, Set as AbstractSet
from dataclasses import dataclass
from enum import Enum, auto
from typing import cast

from django.db import transaction
from django.db.models import Model
from django.test import Client

import pytest
from hypothesis import HealthCheck, Phase, settings, strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    invariant,
    rule,
    run_state_machine_as_test,
)

from testapp.models import Attachment, Folder, Sheet, Shortcut, Tag

from .etags import (
    ServedBodies,
    assert_served_etags_match,
    forget_stored_etags,
    reset_database,
)

# two values each, so writes can restore an earlier state
VALUES = st.sampled_from(["a", "b"])
POSITIONS = st.integers(min_value=0, max_value=1)

MAX_ROWS = 2  # per model, to keep the states small


class Rollback(Exception):
    """Rolls back the atomic block it is raised in."""


class Session:
    """
    One transaction's view of the database, as application code holds it.

    Rows are picked at random. A row loaded earlier in the transaction may be
    reused as the same Python object, possibly with stale attributes, or loaded
    again as a fresh one. After a delete or a rolled-back savepoint the loaded
    objects are forgotten: Django does not restore their pks or related objects,
    and saving them would fail for reasons that have nothing to do with ETags.
    """

    def __init__(self, data: st.DataObject) -> None:
        self.data = data
        self.loaded: dict[tuple[type[Model], int], Model] = {}

    def draw[T](self, strategy: st.SearchStrategy[T], label: str) -> T:
        return self.data.draw(strategy, label=label)

    def pick[M: Model](self, model: type[M]) -> M:
        pks = list(model._default_manager.values_list("pk", flat=True))
        pk = self.draw(st.sampled_from(pks), f"{model.__name__} pk")
        key = (model, pk)
        if key in self.loaded and self.draw(st.booleans(), "reuse loaded object"):
            return cast(M, self.loaded[key])
        obj = self.loaded[key] = model._default_manager.get(pk=pk)
        return obj

    def save(self, obj: Model, field: str) -> None:
        if self.draw(st.booleans(), "update_fields"):
            obj.save(update_fields=[field])
        else:
            obj.save()


type Operation = Callable[[Session], None]


@dataclass(frozen=True)
class Registration:
    """
    An operation, with the rows it needs, the room it needs to make one, and
    whether it deletes rows.
    """

    run: Operation
    needs: frozenset[type[Model]]
    room: type[Model] | None
    deletes: bool

    def applicable(self) -> bool:
        if not all(model._default_manager.exists() for model in self.needs):
            return False
        return self.room is None or self.room._default_manager.count() < MAX_ROWS


OPERATIONS: dict[Operation, Registration] = {}


def operation[Op: Operation](
    *,
    needs: AbstractSet[type[Model]] = frozenset(),
    room: type[Model] | None = None,
    deletes: bool = False,
) -> Callable[[Op], Op]:
    """
    Register an operation.

    :param needs: models it needs a row of
    :param room: the model it needs room for another row of, if any
    :param deletes: whether it deletes rows
    """

    def register(run: Op) -> Op:
        OPERATIONS[run] = Registration(run, frozenset(needs), room, deletes)
        return run

    return register


@operation(room=Folder)
def create_folder(s: Session) -> None:
    Folder.objects.create(name=s.draw(VALUES, "name"), code=s.draw(VALUES, "code"))


@operation(needs={Folder})
def update_folder(s: Session) -> None:
    folder = s.pick(Folder)
    field = s.draw(st.sampled_from(["name", "code"]), "field")
    setattr(folder, field, s.draw(VALUES, field))
    s.save(folder, field)


@operation(needs={Folder}, deletes=True)
def delete_folder(s: Session) -> None:
    s.pick(Folder).delete()


@operation(needs={Folder}, room=Sheet)
def create_sheet(s: Session) -> None:
    Sheet.objects.create(
        folder=s.pick(Folder),
        title=s.draw(VALUES, "title"),
        position=s.draw(POSITIONS, "position"),
    )


@operation(needs={Sheet})
def update_sheet(s: Session) -> None:
    sheet = s.pick(Sheet)
    if s.draw(st.booleans(), "change title (else position)"):
        sheet.title = s.draw(VALUES, "title")
        s.save(sheet, "title")
    else:
        sheet.position = s.draw(POSITIONS, "position")
        s.save(sheet, "position")


@operation(needs={Sheet, Folder})
def move_sheet(s: Session) -> None:
    sheet = s.pick(Sheet)
    sheet.folder = s.pick(Folder)
    s.save(sheet, "folder")


@operation(needs={Sheet})
def touch_sheet(s: Session) -> None:
    s.pick(Sheet).save()


@operation(needs={Sheet}, deletes=True)
def delete_sheet(s: Session) -> None:
    s.pick(Sheet).delete()


@operation(room=Tag)
def create_tag(s: Session) -> None:
    Tag.objects.create(label=s.draw(VALUES, "label"))


@operation(needs={Tag})
def update_tag(s: Session) -> None:
    tag = s.pick(Tag)
    tag.label = s.draw(VALUES, "label")
    s.save(tag, "label")


@operation(needs={Tag}, deletes=True)
def delete_tag(s: Session) -> None:
    s.pick(Tag).delete()


@operation(needs={Tag, Folder})
def tag_folder(s: Session) -> None:
    tag, folder = s.pick(Tag), s.pick(Folder)
    if s.draw(st.booleans(), "from the tag's side"):
        tag.folders.add(folder)
    else:
        folder.tags.add(tag)


@operation(needs={Tag, Folder})
def untag_folder(s: Session) -> None:
    tag, folder = s.pick(Tag), s.pick(Folder)
    if s.draw(st.booleans(), "from the tag's side"):
        tag.folders.remove(folder)
    else:
        folder.tags.remove(tag)


@operation(needs={Tag})
def clear_tag(s: Session) -> None:
    s.pick(Tag).folders.clear()


@operation(needs={Folder})
def clear_folder_tags(s: Session) -> None:
    s.pick(Folder).tags.clear()


@operation(needs={Tag})
def set_tag_folders(s: Session) -> None:
    tag = s.pick(Tag)
    folders = list(Folder.objects.all())
    chosen = st.lists(st.sampled_from(folders), unique=True) if folders else st.just([])
    tag.folders.set(s.draw(chosen, "folders"))


@operation(needs={Folder}, room=Attachment)
def create_attachment(s: Session) -> None:
    Attachment.objects.create(
        folder=s.pick(Folder), filename=s.draw(VALUES, "filename")
    )


@operation(needs={Attachment})
def update_attachment(s: Session) -> None:
    attachment = s.pick(Attachment)
    attachment.filename = s.draw(VALUES, "filename")
    s.save(attachment, "filename")


@operation(needs={Attachment}, deletes=True)
def delete_attachment(s: Session) -> None:
    s.pick(Attachment).delete()


@operation(room=Shortcut)
def create_shortcut(s: Session) -> None:
    with_target = Folder.objects.exists() and s.draw(st.booleans(), "with a target")
    Shortcut.objects.create(
        label=s.draw(VALUES, "label"), target=s.pick(Folder) if with_target else None
    )


@operation(needs={Shortcut})
def update_shortcut(s: Session) -> None:
    shortcut = s.pick(Shortcut)
    if s.draw(st.booleans(), "change label (else target)"):
        shortcut.label = s.draw(VALUES, "label")
        s.save(shortcut, "label")
    else:
        with_target = Folder.objects.exists() and s.draw(st.booleans(), "with a target")
        shortcut.target = s.pick(Folder) if with_target else None
        s.save(shortcut, "target")


@operation(needs={Shortcut}, deletes=True)
def delete_shortcut(s: Session) -> None:
    s.pick(Shortcut).delete()


class Nesting(Enum):
    PLAIN = auto()
    SAVEPOINT = auto()
    ROLLED_BACK_SAVEPOINT = auto()


def seed() -> None:
    """
    Two folders and a row of every other model, so every operation applies from
    the first transaction: a move, say, needs a sheet and a folder to move it to.
    """
    first, second = (Folder.objects.create(name="a", code="a") for _ in range(2))
    Sheet.objects.create(folder=first, title="a", position=0)
    Tag.objects.create(label="a").folders.add(second)
    Attachment.objects.create(folder=first, filename="a")
    Shortcut.objects.create(label="a", target=second)


class EtagOracle(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        reset_database()
        seed()
        self.client = Client()
        self.served = ServedBodies()

    @rule(data=st.data())
    def run_transaction(self, data: st.DataObject) -> None:
        """One transaction of up to three operations, each in or out of a savepoint."""
        # one in four, so most transactions write over ETags a GET filled in
        if data.draw(st.sampled_from([False, False, False, True]), label="upgrade"):
            forget_stored_etags()
        session = Session(data)
        try:
            with transaction.atomic():
                for _ in range(data.draw(st.integers(1, 3), label="operations")):
                    # drawn from the operations that apply, so no draw is wasted
                    applicable = [
                        run
                        for run, registration in OPERATIONS.items()
                        if registration.applicable()
                    ]
                    run = data.draw(st.sampled_from(applicable), label="operation")
                    registration = OPERATIONS[run]
                    nesting = data.draw(st.sampled_from(Nesting), label=run.__name__)
                    if nesting is Nesting.PLAIN:
                        registration.run(session)
                    else:
                        try:
                            with transaction.atomic():
                                registration.run(session)
                                if nesting is Nesting.ROLLED_BACK_SAVEPOINT:
                                    raise Rollback
                        except Rollback:
                            pass
                    if registration.deletes or nesting is Nesting.ROLLED_BACK_SAVEPOINT:
                        session.loaded.clear()
                if data.draw(st.booleans(), label="roll back the transaction"):
                    raise Rollback
        except Rollback:
            pass

    @invariant()
    def served_etags_match_representations(self) -> None:
        assert_served_etags_match(self.client, self.served)


@pytest.mark.django_db(transaction=True)
def test_served_etags_match_representations(etag_api: None, quiet_logs: None) -> None:
    run_state_machine_as_test(
        EtagOracle,
        settings=settings(
            max_examples=int(os.getenv("ETAG_ORACLE_EXAMPLES", "200")),
            stateful_step_count=6,
            deadline=None,
            phases=[Phase.explicit, Phase.reuse, Phase.generate, Phase.shrink],
            suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
        ),
    )
