"""
Conditional GET: send the ETag of the selected representation, and answer a
matching ``If-None-Match`` with 304.

.. code-block:: text

    GET /zaken/1                             200  ETag: "a1b2…"
    GET /zaken/1   If-None-Match: "a1b2…"    304  ETag: "a1b2…"
    GET /zaken/1?expand=rollen               200  no ETag: another representation
    GET /zaken/2   If-None-Match: *          404  no ETag: not for this client
"""

from collections.abc import Callable, Generator, Set as AbstractSet
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial, wraps

from django.db import DEFAULT_DB_ALIAS, models, transaction
from django.utils.http import parse_etags

from rest_framework.response import Response

from .etags import calculate_etag
from .store import Resource, current_stamp, fill, read

type Handler = Callable[..., Response]


@dataclass(frozen=True)
class ETag:
    """
    The ETag of a representation.

    :param value: the entity tag, unquoted
    :param fill: stores ``value``, if it was calculated rather than stored; call it
      after the :func:`snapshot`
    """

    value: str
    fill: Callable[[], None] | None


def conditional(handler: Handler, variant_params: AbstractSet[str]) -> Handler:
    """
    Wrap a viewset's retrieve handler.

    The object is retrieved first, through the viewset's queryset and permissions,
    so a client that may not see it gets the same 404 or 403 whether or not the
    request is conditional. The ETag and the body are read in one :func:`snapshot`.
    A request with one of ``variant_params`` selects another representation; it is
    handled as is, without ETag.
    """

    @wraps(handler)
    def conditional_handler(self, request, *args, **kwargs) -> Response:
        if not variant_params.isdisjoint(request.query_params):
            return handler(self, request, *args, **kwargs)

        with snapshot():
            instance = self.get_object()  # a 404 or 403 comes before anything else
            etag = current_etag(instance)
            header = f'"{etag.value}"'
            condition = request.headers.get("If-None-Match")
            if condition is not None and none_match(condition, etag.value):
                response = Response(status=304, headers={"ETag": header})
            else:
                response = handler(self, request, *args, **kwargs)
                if response.status_code == 200:
                    response["ETag"] = header
        # after the snapshot: a write to fill with is not allowed in it
        if etag.fill is not None:
            etag.fill()
        return response

    return conditional_handler


@contextmanager
def snapshot(using: str = DEFAULT_DB_ALIAS) -> Generator[None]:
    """
    Read in one REPEATABLE READ, read-only transaction, so the ETag and the body
    describe the same data. In a transaction already (``ATOMIC_REQUESTS``, tests),
    read in that one.
    """
    if transaction.get_connection(using).in_atomic_block:
        yield
        return
    with transaction.atomic(using=using):
        # only allowed before the first query of the transaction
        with transaction.get_connection(using).cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        yield


def current_etag(instance: models.Model) -> ETag:
    """
    The ETag of the instance's representation: the stored one if filled under the
    current stamp, else calculated.

    The stored ETag is read before the representation is serialized, so the token
    a fill compares with predates the data it serialized.
    """
    model = type(instance)
    resource = Resource(model, instance.pk)
    stored = read(resource)
    stamp = current_stamp()
    if stored is not None and stored.etag is not None and stored.stamp == stamp:
        return ETag(stored.etag, None)
    # ``instance`` was loaded before the token was read; in READ COMMITTED (a
    # caller's transaction rather than our snapshot) a write may have come between
    value = calculate_etag(model._base_manager.get(pk=instance.pk))
    token = None if stored is None else stored.token
    return ETag(value, partial(fill, resource, token, value, stamp))


def _opaque(tag: str) -> str:
    """
    The entity tag without ``W/`` and quotes: ``W/"a1b2"`` is ``a1b2``.

    Weak comparison matches tags whose opaque values are equal.
    """
    return tag.removeprefix("W/").strip('"')


def none_match(header: str, etag: str) -> bool:
    """
    Whether an ``If-None-Match`` header is ``*`` or lists ``etag``, compared weakly
    (RFC 9110, 13.1.2).
    """
    if header.strip() == "*":
        return True
    return _opaque(etag) in {_opaque(tag) for tag in parse_etags(header)}
