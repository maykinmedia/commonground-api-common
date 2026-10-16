"""
Stored ETags.

A write replaces the stored ETag of every resource it affects with a fresh token,
inside its own transaction. A GET that finds a token calculates the ETag and fills
it in with a compare-and-set on that token, so a write since the GET read the token
wins. ``specs/etag/EtagToken.tla`` model-checks this protocol.

.. code-block:: python

    invalidate({Resource(Folder, 1)})  # in the writing transaction
    stored = read(Resource(Folder, 1))  # Stored(token=UUID(...), etag=None, stamp="")
    fill(Resource(Folder, 1), stored.token, etag, current_stamp())  # no-op if written since

In :func:`batched_invalidation`, writes collect the tokens to write, and its end
writes them in one statement, before the transaction commits.
"""

from __future__ import annotations

import hashlib
import json
import operator
from collections.abc import Collection, Generator, Hashable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import reduce
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.postgres.functions import RandomUUID
from django.db import models, transaction

import vng_api_common

from ..utils import get_domain

if TYPE_CHECKING:
    from .models import StoredETag


@dataclass(frozen=True)
class Resource:
    """A resource, by model and primary key."""

    model: type[models.Model]
    pk: Hashable


@dataclass(frozen=True)
class Stored:
    """
    A stored ETag.

    :param token: replaced by every write that affects the resource
    :param etag: the ETag filled in for ``token``, if any
    :param stamp: the :func:`current_stamp` ``etag`` was calculated under
    """

    token: UUID
    etag: str | None
    stamp: str


def _model() -> type[StoredETag]:
    # imported late: ``.models`` imports ``.etags``, which imports the registry,
    # which imports this module
    from .models import StoredETag

    return StoredETag


def _label(model: type[models.Model]) -> str:
    """The ``model`` of its resources' rows: a proxy model shares its concrete one's."""
    return (model._meta.concrete_model or model)._meta.label_lower


def _key(resource: Resource) -> tuple[str, str]:
    """The ``model`` and ``object_id`` of the resource's row: ``"testapp.folder", "1"``."""
    return _label(resource.model), str(resource.pk)


def _lookup(resource: Resource) -> dict[str, str]:
    label, object_id = _key(resource)
    return {"model": label, "object_id": object_id}


def current_stamp() -> str:
    """
    A digest of what a representation depends on besides the data: the release of
    this library, the project's release in ``ETAG_REPRESENTATION_VERSION``, and the
    domain and scheme of hyperlinks.

    A stored ETag with another stamp is calculated anew: another release or
    another domain may represent the same data differently.
    """
    # JSON, so no value can run into the next
    parts = [
        vng_api_common.__version__,
        getattr(settings, "ETAG_REPRESENTATION_VERSION", ""),
        get_domain(),
        "https" if settings.IS_HTTPS else "http",
    ]
    return hashlib.md5(json.dumps(parts).encode()).hexdigest()


def read(resource: Resource) -> Stored | None:
    """
    The stored ETag of ``resource``; ``None`` if no write has affected it since it
    was stored, or ever.
    """
    columns = (
        _model()
        .objects.filter(**_lookup(resource))
        .values_list("token", "etag", "stamp")
    )
    row = columns.first()
    return None if row is None else Stored(*row)


@dataclass
class _Batch:
    """The rows the writes in a batch invalidated, and those of resources deleted."""

    invalidated: set[tuple[str, str]] = field(default_factory=set)
    deleted: set[tuple[str, str]] = field(default_factory=set)


_batch: ContextVar[_Batch | None] = ContextVar("batch", default=None)


@contextmanager
def batched_invalidation(*, savepoint: bool = True) -> Generator[None]:
    """
    Make a loop of writes cheaper: every write invalidates the ETags it affects
    with a query of its own, and in this block all of them share one.

    .. code-block:: python

        with batched_invalidation():
            for zaak in gerelateerde_zaken:
                RelevanteZaakRelatie.objects.create(zaak=zaak, url=url)

    Use it where one request writes many rows, such as a create with nested
    relations. The block is a transaction, as in ``transaction.atomic()``: an
    exception rolls back its writes. It nests in transactions and in itself.
    Clients see the same ETags as without it.

    Inside a transaction, ``savepoint=False`` saves the two queries of a
    savepoint, as it does for ``transaction.atomic``: an exception in the block
    then rolls back the whole transaction.
    """
    # The writes in the block collect the rows to invalidate, and the block's end
    # writes their tokens, before the transaction commits. Until then the writes
    # don't lock the stored ETags, so a GET may fill one in from the committed data;
    # the end replaces it. ``specs/etag/EtagToken.tla`` checks this (BatchedTxs).
    # Rows of writes rolled back to a savepoint are invalidated too: needlessly,
    # but safely. The rows of deleted resources are deleted at the end too, as a
    # rollback to a savepoint undoes a delete but not what the batch collected; a
    # resource that exists again has no stored ETag then, which is as safe as a
    # token. A nested block only opens a savepoint, and the outermost writes.
    if _batch.get() is not None:
        with transaction.atomic(savepoint=savepoint):
            yield
        return
    batch = _Batch()
    token = _batch.set(batch)
    try:
        with transaction.atomic(savepoint=savepoint):
            yield
            _batch.reset(token)
            token = None
            _delete_rows(batch.deleted)
            _write_tokens(batch.invalidated - batch.deleted)
    finally:
        if token is not None:
            _batch.reset(token)


def invalidate(resources: Collection[Resource]) -> None:
    """
    Replace the stored ETags of ``resources`` with fresh tokens, in one statement in
    the current transaction, or at the end of the :func:`batched_invalidation`
    around it.
    """
    keys = {_key(resource) for resource in resources}
    if (batch := _batch.get()) is not None:
        batch.invalidated.update(keys)
    else:
        _write_tokens(keys)


def invalidate_all(resource_models: Collection[type[models.Model]]) -> None:
    """
    Replace every stored ETag, or those of the resources of ``resource_models``,
    with a fresh token, in one statement in the current transaction.
    """
    # It locks every row it writes until the transaction ends, in no particular
    # order: a writer that meets it may deadlock, and PostgreSQL then aborts one.
    rows = _model().objects.all()
    if resource_models:
        rows = rows.filter(model__in={_label(model) for model in resource_models})
    rows.update(token=RandomUUID(), etag=None, stamp="")


def _write_tokens(keys: Collection[tuple[str, str]]) -> None:
    """
    Write fresh tokens to the rows of ``keys``, in one statement, in a canonical
    order (model, then primary key), so concurrent writers lock them in the same
    order.
    """
    # PostgreSQL inserts the rows of ``UNNEST`` in array order, and an ``ON
    # CONFLICT`` locks each existing row as it comes to it. SQL doesn't promise that
    # order; if another one came about, PostgreSQL detects the deadlock and aborts
    # one writer, so in a transaction it costs a failed write, not a stale ETag.
    if not keys:
        return
    table = _model()
    table.objects.bulk_create(
        [
            table(
                model=label,
                object_id=object_id,
                token=uuid4(),
                etag=None,
                stamp="",
            )
            for label, object_id in sorted(keys)
        ],
        update_conflicts=True,
        unique_fields=["model", "object_id"],
        update_fields=["token", "etag", "stamp"],
    )


def fill(resource: Resource, token: UUID | None, etag: str, stamp: str) -> None:
    """
    Store ``etag``, calculated after reading ``token``, unless a write replaced the
    token since.

    With ``token=None``, store it only if no row exists yet: if a writer is
    inserting one, wait for it, and leave its row. A fill with a token never waits
    for a writer: the stored ETag is the writer's to replace.
    """
    table = _model()
    # in a transaction or savepoint of its own: a failed fill leaves an enclosing
    # transaction usable
    with transaction.atomic():
        if token is None:
            row = table(**_lookup(resource), token=uuid4(), etag=etag, stamp=stamp)
            table.objects.bulk_create([row], ignore_conflicts=True)
            return
        # a writer holding the row's lock replaces the token: skip it, don't wait
        unlocked = (
            table.objects.filter(**_lookup(resource), token=token)
            .select_for_update(skip_locked=True)
            .values("pk")
        )
        table.objects.filter(pk__in=unlocked).update(etag=etag, stamp=stamp)


def forget(resource: Resource) -> None:
    """
    Delete the stored ETag of a deleted resource, in the current transaction, or at
    the end of the :func:`batched_invalidation` around it.
    """
    if (batch := _batch.get()) is not None:
        batch.deleted.add(_key(resource))
    else:
        _delete_rows({_key(resource)})


def _delete_rows(keys: Collection[tuple[str, str]]) -> None:
    """Delete the rows of ``keys``, in one statement."""
    if not keys:
        return
    rows = reduce(
        operator.or_,
        (models.Q(model=label, object_id=object_id) for label, object_id in keys),
    )
    _model().objects.filter(rows).delete()
