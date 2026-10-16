============
HTTP Caching
============

HTTP caching is a mechanism that shines in RESTful APIs. A ``GET`` or ``HEAD``
response on a detail resource can be augmented with the ``ETag`` header, which
essentially is a "version" of a resource. Every modification of the resource
leads to a new version.

This can be leveraged in combination with the ``If-None-Match`` request header,
known as conditional requests.

The client includes the ``ETag`` value(s) in this header, and if the current
version of the resource has the same ``ETag`` value, then the server replies
with an ``HTTP 304`` response, indicating that the content has not changed.

This allows consumers to send less data over the wire without having to
perform extra requests if they keep resources in their own cache.

See the `ETag on MDN`_ documentation for the full specification.

Implementing conditional requests
=================================

Decorate the viewset
--------------------

Decorating the viewset retrieve ensures that the ``ETag`` header is set,
the conditional request handling (HTTP 200 vs. HTTP 304) is performed and the
extra methods/headers show up in the generated API schema.

.. code-block:: python
    :linenos:

    from rest_framework import viewsets
    from vng_api_common.caching import conditional_retrieve

    from .models import MyModel
    from .serializers import MyModelSerializer


    @conditional_retrieve()
    class MyModelViewSet(viewsets.ReadOnlyViewSet):
        queryset = MyModel.objects.all()
        serializer_class = MyModelSerializer

The serializer is introspected for the relations the representation reads. Name
the ones it can't see, such as those a ``SerializerMethodField`` reads, and the
query parameters that select another representation:

.. code-block:: python

    @conditional_retrieve(extra_depends_on={"rollen"}, variant_params={"expand"})
    class ZaakViewSet(viewsets.ReadOnlyModelViewSet): ...

Responses to requests with a variant parameter get no ETag.

Writing
-------

Saves and deletes keep ETags right by themselves: once a write commits, every
resource it changed has a new ETag. Writes don't calculate ETags; the first
``GET`` after them does, once, however many writes came before.

Write in a transaction. Outside one, a ``GET`` that runs during a save can get
an ETag that doesn't match the saved data.

Writes that send no signals
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``QuerySet.update``, ``bulk_create``, ``bulk_update`` and raw SQL send no model
signals, so they don't invalidate anything and may result in stale ETags: clients
keep getting 304s for resources they changed. Make up for it in the same
transaction as the write.

Instead of ``QuerySet.update``, use
:func:`~vng_api_common.caching.invalidating_update`:

.. code-block:: python

    from vng_api_common.caching import invalidating_update

    invalidating_update(Zaak.objects.filter(pk=zaak.pk), archiefactiedatum=None)

After ``bulk_create``, pass the new objects to
:func:`~vng_api_common.caching.invalidate_etags`:

.. code-block:: python

    from vng_api_common.caching import invalidate_etags

    with transaction.atomic():
        zios = ZaakInformatieObject.objects.bulk_create(
            [ZaakInformatieObject(zaak=zaak, informatieobject=url) for url in urls]
        )
        invalidate_etags(*zios)

Around ``bulk_update``, call it after, and before as well when the update changes
a ``ForeignKey``: the objects' old parents need new ETags too.

.. code-block:: python

    with transaction.atomic():
        invalidate_etags(*zios)  # their old zaken
        for zio in zios:
            zio.zaak = other_zaak
        ZaakInformatieObject.objects.bulk_update(zios, ["zaak"])
        invalidate_etags(*zios)  # their new zaak

After raw SQL, :func:`~vng_api_common.caching.invalidate_all_etags` invalidates
the stored ETags of the resource models you pass, or all of them. It is one
``UPDATE`` that row-locks every stored ETag it covers until commit; pass the
models whose API representation shows the columns you wrote, not the tables:

.. code-block:: python

    from vng_api_common.caching import invalidate_all_etags

    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("UPDATE zaken_zaak SET archiefstatus = 'gearchiveerd' ...")
        invalidate_all_etags(Zaak)

Many writes
~~~~~~~~~~~

Every write sends a query of its own to invalidate the ETags it affects. Where a
request writes many rows, run the writes in
:func:`~vng_api_common.caching.batched_invalidation`, a transaction in which they
share one:

.. code-block:: python

    from vng_api_common.caching import batched_invalidation

    with batched_invalidation():
        for zaak in gerelateerde_zaken:
            RelevanteZaakRelatie.objects.create(zaak=zaak, url=url)

Inside a transaction, ``batched_invalidation(savepoint=False)`` skips the
savepoint, as ``transaction.atomic(savepoint=False)`` does.

Releases and settings
~~~~~~~~~~~~~~~~~~~~~

Set ``ETAG_REPRESENTATION_VERSION`` to your project's release, so that a
release that represents resources differently gets new ETags. Releases of this
library do so by themselves.

.. code-block:: python

    ETAG_REPRESENTATION_VERSION = openzaak.__version__

.. warning:: Don't serve conditional requests with ``ATOMIC_REQUESTS``: a
   client may get a 304 for a body that changed. A ``GET`` needs the ETag and the
   body from one snapshot of the data, which it can't take inside the request's
   transaction.

Upgrading
---------

In a rolling deploy, old processes write without invalidating stored ETags. Once
the last one has stopped, clear them, or clients may get a 304 for a changed
resource:

.. code-block:: bash

    python manage.py shell -c "from vng_api_common.caching.models import StoredETag; StoredETag.objects.all().delete()"

Migration ``0008`` creates the ``StoredETag`` table. The first ``GET`` of a
resource after the upgrade calculates its ETag.

:class:`~vng_api_common.caching.ETagMixin` is deprecated: new models don't need it.
Its ``_etag`` column is no longer maintained. Drop it from your models in two
releases, so a rolling deploy keeps working:

1. Remove the field from the model state only, and give the column a database
   default, as old processes still insert it and new ones don't:

   .. code-block:: python

       migrations.SeparateDatabaseAndState(
           database_operations=[
               migrations.RunSQL(
                   "ALTER TABLE zaken_zaak ALTER COLUMN _etag SET DEFAULT ''",
                   "ALTER TABLE zaken_zaak ALTER COLUMN _etag DROP DEFAULT",
               )
           ],
           state_operations=[migrations.RemoveField("zaak", "_etag")],
       )

2. Drop the column in the next release:

   .. code-block:: python

       migrations.RunSQL(
           "SET LOCAL lock_timeout = '5s'; ALTER TABLE zaken_zaak DROP COLUMN _etag"
       )

``makemigrations`` generates a plain ``RemoveField``, which drops the column while
old processes still select it. The check ``vng_api_common.caching.W001`` warns
about one when ``migrate`` runs.


Public API
==========

.. automodule:: vng_api_common.caching
    :members:


.. _ETag on MDN: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/ETag
