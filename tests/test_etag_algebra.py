"""
Laws of the primitives that decide what a write invalidates.

:class:`Dependency` values form a small algebra: ``merge`` joins what two
dependencies of one lookup read, and ``reads`` and ``moves`` say whether a save
writing some columns concerns them. The fast paths are checked against the
definitions, on testapp's registry and data drawn by hypothesis: reading a
parent off the instance, finding resources for many rows at once, narrowing a
save to its ``update_fields``, and updating in bulk.
"""

from collections.abc import Iterator
from functools import reduce
from unittest.mock import patch

from django.db.models import Model

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from testapp.models import Attachment, Folder, Sheet, Shortcut, Tag
from vng_api_common.caching import invalidating_update
from vng_api_common.caching.registry import (
    ALL,
    DEPENDENCY_REGISTRY,
    Columns,
    Dependency,
    affected,
    affected_by_save,
    before_save,
    overlap,
)
from vng_api_common.caching.store import Resource

from .etags import reset_database

COLUMNS = ("a", "b", "c")
columns: st.SearchStrategy[Columns] = st.just(ALL) | st.frozensets(
    st.sampled_from(COLUMNS)
)
# one lookup, so any two merge; its parent follows from the lookup
dependencies = st.builds(
    Dependency,
    resource=st.just(Folder),
    lookup=st.just("sheets"),
    membership=columns,
    shown=columns,
    parent=st.just(None),
    enforced=st.booleans(),
)


@given(columns, columns)
def test_a_union_of_columns_commutes(a: Columns, b: Columns):
    assert a | b == b | a


@given(columns, columns, columns)
def test_a_union_of_columns_associates(a: Columns, b: Columns, c: Columns):
    assert (a | b) | c == a | (b | c)


@given(columns)
def test_all_columns_bound_every_union(a: Columns):
    assert a | a == a
    assert a | frozenset() == a
    assert a | ALL == ALL
    assert all(name in ALL for name in COLUMNS)


@given(columns, columns, columns)
def test_overlap_is_symmetric_and_distributes_over_union(
    a: Columns, b: Columns, c: Columns
):
    assert overlap(a, b) == overlap(b, a)
    assert overlap(a, b | c) == (overlap(a, b) or overlap(a, c))
    assert overlap(a, ALL) == (a != frozenset())


@given(dependencies, dependencies)
def test_merge_commutes(a: Dependency, b: Dependency):
    assert a.merge(b) == b.merge(a)


@given(dependencies, dependencies, dependencies)
def test_merge_associates(a: Dependency, b: Dependency, c: Dependency):
    assert a.merge(b).merge(c) == a.merge(b.merge(c))


@given(dependencies)
def test_merge_is_idempotent(a: Dependency):
    assert a.merge(a) == a


@given(dependencies, dependencies, columns)
def test_a_merge_concerns_a_save_when_either_part_does(
    a: Dependency, b: Dependency, written: Columns
):
    merged = a.merge(b)
    assert merged.reads(written) == (a.reads(written) or b.reads(written))
    assert merged.moves(written) == (a.moves(written) or b.moves(written))


@given(dependencies, columns, columns)
def test_writing_more_concerns_more(a: Dependency, written: Columns, more: Columns):
    assert a.reads(written) <= a.reads(written | more)
    assert a.moves(written) <= a.moves(written | more)
    assert a.reads(written) <= a.reads(ALL)


@given(dependencies, columns)
def test_a_save_that_may_move_a_row_may_change_what_reads_it(
    a: Dependency, written: Columns
):
    assert a.moves(written) <= a.reads(written)


# testapp's registry, on data drawn by hypothesis

LABELS = st.sampled_from("ab")
data_settings = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)


@st.composite
def written_data(draw: st.DrawFn) -> None:
    """Folders, and sheets, tags, attachments and shortcuts between them."""
    reset_database()
    folders = [
        Folder.objects.create(name=draw(LABELS), code=draw(LABELS))
        for _ in range(draw(st.integers(1, 3)))
    ]
    some_folder = st.sampled_from(folders)
    for position in range(draw(st.integers(0, 3))):
        Sheet.objects.create(
            folder=draw(some_folder), title=draw(LABELS), position=position
        )
    for _ in range(draw(st.integers(0, 2))):
        tag = Tag.objects.create(label=draw(LABELS))
        tag.folders.set(draw(st.lists(some_folder, unique_by=lambda f: f.pk)))
    for _ in range(draw(st.integers(0, 2))):
        Attachment.objects.create(folder=draw(some_folder), filename=draw(LABELS))
    for _ in range(draw(st.integers(0, 2))):
        Shortcut.objects.create(
            label=draw(LABELS), target=draw(st.none() | some_folder)
        )


def registered_rows() -> Iterator[tuple[Dependency, Model]]:
    """Each registered dependency, with each row of its source, fresh."""
    for source, registered in DEPENDENCY_REGISTRY.items():
        for dependency in registered:
            for row in source._base_manager.all():
                yield dependency, row


def fields_of(model: type[Model]) -> st.SearchStrategy[frozenset[str]]:
    names = [f.name for f in model._meta.concrete_fields if not f.primary_key]
    return st.frozensets(st.sampled_from(names))


pytestmark = pytest.mark.usefixtures("etag_api")


@pytest.mark.django_db(transaction=True)
@data_settings
@given(written_data())
def test_reading_the_parent_off_a_fresh_row_finds_what_the_lookup_does(_: None):
    for dependency, row in registered_rows():
        assert dependency.parent_of(row, ALL) == dependency.resources(row)


@pytest.mark.django_db(transaction=True)
@data_settings
@given(written_data())
def test_resources_of_many_rows_are_those_of_each(_: None):
    for source, registered in DEPENDENCY_REGISTRY.items():
        rows = list(source._base_manager.all())
        for dependency in registered:
            each = frozenset[Resource]().union(*map(dependency.resources, rows))
            assert dependency.resources_of([row.pk for row in rows]) == each


@pytest.mark.django_db(transaction=True)
@data_settings
@given(written_data(), st.data())
def test_a_save_of_some_columns_affects_no_more_than_one_of_all_or_a_delete(
    _: None, data: st.DataObject
):
    for model in (Folder, Sheet, Tag, Attachment, Shortcut):
        for row in model._base_manager.all():
            written = data.draw(fields_of(model), label=f"{model.__name__} fields")
            # a save can't change a primary key, which some resources show alone
            everything = affected_by_save(row, ALL, created=False)
            assert affected_by_save(row, written, created=False) <= everything
            assert everything <= affected(row)
            registered = DEPENDENCY_REGISTRY.get(model, ())
            assert {d for d in registered if d.moves(written)} <= set(
                before_save(model, written)
            )


@pytest.mark.django_db(transaction=True)
@data_settings
@given(written_data(), st.data())
def test_an_update_in_bulk_invalidates_what_saving_each_row_would(
    _: None, data: st.DataObject
):
    """
    Saving each row with ``update_fields`` invalidates, before the save, the
    resources the row may leave, and after it, those its new columns concern.
    """
    if not Sheet.objects.exists():
        return
    field = data.draw(st.sampled_from(["folder", "title", "position"]), label="field")
    value = {
        "folder": lambda: data.draw(st.sampled_from(list(Folder.objects.all()))),
        "title": lambda: data.draw(LABELS),
        "position": lambda: data.draw(st.integers(0, 3)),
    }[field]()
    rows = Sheet.objects.filter(title=data.draw(LABELS, label="title selected"))
    written = frozenset({field})
    before = reduce(
        frozenset.union,
        (d.resources(row) for row in rows for d in before_save(Sheet, written)),
        frozenset(),
    )

    invalidated: set[Resource] = set()
    with patch(
        "vng_api_common.caching.bulk.invalidate", side_effect=invalidated.update
    ):
        pks = list(rows.values_list("pk", flat=True))
        invalidating_update(rows, **{field: value})

    after = reduce(
        frozenset.union,
        (
            affected_by_save(row, written, created=False)
            for row in Sheet.objects.filter(pk__in=pks)
        ),
        frozenset(),
    )
    assert before | after <= invalidated
