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
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Hashable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.conf import settings
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


def _key(resource: Resource) -> tuple[str, str]:
    """
    The ``model`` and ``object_id`` of the resource's row: ``"testapp.folder", "1"``.
    A proxy model shares the row of its concrete model.
    """
    concrete = resource.model._meta.concrete_model or resource.model
    return concrete._meta.label_lower, str(resource.pk)


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


def invalidate(resources: Collection[Resource]) -> None:
    """
    Replace the stored ETags of ``resources`` with fresh tokens, in one statement in
    the current transaction.

    The rows are written in a canonical order (model, then primary key), so
    concurrent writers lock them in the same order.
    """
    # PostgreSQL inserts the rows of ``UNNEST`` in array order, and an ``ON
    # CONFLICT`` locks each existing row as it comes to it. SQL doesn't promise that
    # order; if another one came about, PostgreSQL detects the deadlock and aborts
    # one writer, so in a transaction it costs a failed write, not a stale ETag.
    keys = sorted({_key(resource) for resource in resources})
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
            for label, object_id in keys
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
    """Delete the stored ETag of a deleted resource."""
    _model().objects.filter(**_lookup(resource)).delete()
