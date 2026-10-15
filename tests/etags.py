"""
What the ETag tests share: the resources, a blank start, and the checks that every
resource serves the ETag of its current representation and that an ETag never
comes with two bodies.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import connection, transaction
from django.db.models import Model
from django.test import Client
from django.urls import reverse

from testapp.models import Folder, Sheet, Shortcut, Tag
from vng_api_common.caching import calculate_etag

if TYPE_CHECKING:  # what the test client returns
    from django.test.client import _MonkeyPatchedWSGIResponse as Response

RESOURCES: dict[type[Model], str] = {
    Folder: "folder-detail",
    Sheet: "sheet-detail",
    Tag: "tag-detail",
    Shortcut: "shortcut-detail",
}

# rows that follow from the installed apps, which flush would recreate
KEPT_TABLES = frozenset({ContentType._meta.db_table, Permission._meta.db_table})


def reset_database() -> None:
    """
    Reset the database to the blank state transactional tests start from: the rows
    of every model deleted and pks restarting at 1. Content types and permissions
    are kept: ``flush`` would only recreate them, and takes 20 times as long.
    """
    # The stateful hypothesis examples test behaviour across db transactions.
    # Resetting the database is so any failures come from the interleavings in
    # the hypothesis example, not from an unknown starting db state.
    tables = [
        table
        for table in connection.introspection.django_table_names(
            only_existing=True, include_views=False
        )
        if table not in KEPT_TABLES
    ]
    with transaction.atomic(), connection.cursor() as cursor:
        # Django's foreign keys are deferred: checked at commit, when all rows are gone
        cursor.execute(
            "".join(f"DELETE FROM {connection.ops.quote_name(t)};" for t in tables)
        )
        cursor.execute(
            "SELECT setval(d.objid, 1, false) FROM pg_depend d"
            " JOIN pg_class s ON s.oid = d.objid"
            " WHERE s.relkind = 'S' AND d.refobjid = ANY(%s::regclass[])",
            [tables],
        )


def detail_url(model: type[Model], pk: int) -> str:
    return reverse(RESOURCES[model], kwargs={"pk": pk})


def current_etag(model: type[Model], pk: int) -> str:
    """The ETag of the row's current representation, quoted."""
    return f'"{calculate_etag(model._default_manager.get(pk=pk))}"'


class ServedBodies:
    """
    The body each resource was served with under each ETag. An ETag is a strong
    validator, which changes whenever the representation does (RFC 9110, 8.8.1), so
    it never comes with two bodies: a client caches the body under the ETag, and
    trusts it for as long as a GET conditional on that ETag gets a 304.
    """

    def __init__(self) -> None:
        self._bodies: dict[tuple[str, str], bytes] = {}
        self._lock = threading.Lock()  # concurrent workers record

    def record(self, path: str, etag: str | None, body: bytes) -> None:
        """Record a 200 for ``path``; its ETag must not have come with another body."""
        assert etag is not None, f"{path} is served without an ETag"
        with self._lock:
            first = self._bodies.setdefault((path, etag), body)
        assert body == first, (
            f"{path} serves ETag {etag} with two bodies:\n"
            f"{first.decode()}\n{body.decode()}"
        )


def assert_served_etags_match(client: Client, served: ServedBodies) -> None:
    """
    A GET is answered with the ETag of the current representation, and a GET
    conditional on that ETag with 304 and that ETag, and so is a conditional HEAD.
    """
    for model in RESOURCES:
        for pk in model._default_manager.values_list("pk", flat=True):
            expected, path = current_etag(model, pk), detail_url(model, pk)

            response = client.get(path)
            assert (response.status_code, response.get("ETag")) == (200, expected), (
                f"{model.__name__} {pk} serves ETag {response.get('ETag')}, "
                f"its representation hashes to {expected}"
            )
            served.record(path, response.get("ETag"), response.content)

            condition = {"If-None-Match": expected}
            response = client.get(path, headers=condition)
            assert (response.status_code, response.get("ETag")) == (304, expected), (
                f"{model.__name__} {pk} answers If-None-Match with ETag "
                f"{response.get('ETag')}, its representation hashes to {expected}"
            )
            assert_head_matches(client.head(path, headers=condition), response)


def assert_head_matches(head: Response, get: Response) -> None:
    """A HEAD gets the status and ETag of its GET, and no body (RFC 9110, 9.3.2)."""
    assert (head.status_code, head.get("ETag")) == (get.status_code, get.get("ETag"))
    assert head.content == b""
