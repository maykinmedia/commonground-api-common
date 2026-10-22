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

    class ZaakSerializer(serializers.HyperlinkedModelSerializer):
        initiator = serializers.SerializerMethodField()

        def get_initiator(self, zaak) -> str:
            # reads the zaak's rollen, which no field of the serializer declares
            rol = zaak.rollen.filter(omschrijving_generiek="initiator").first()
            return rol.betrokkene if rol else ""


    # so a write to a rol changes the ETag of its zaak
    @conditional_retrieve(extra_depends_on={"rollen"}, variant_params={"expand"})
    class ZaakViewSet(viewsets.ReadOnlyModelViewSet):
        serializer_class = ZaakSerializer

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

Run a change or delete of a child that also saves its parent in one too, such as
updating a zaakinformatieobject, which updates its zaak's ``laatst_gemuteerd``.
Outside a batch, it can deadlock with a save of that zaak. Nothing hangs:
PostgreSQL detects the deadlock after about a second (its ``deadlock_timeout``),
cancels one of the two transactions and lets the other finish. Nothing the
cancelled request wrote is kept:

.. code-block:: python

    with batched_invalidation():
        zio.titel = titel
        zio.save()
        zaak.laatst_gemuteerd = timezone.now()
        zaak.save(update_fields=["laatst_gemuteerd"])

Adding a child, or saving a new parent into its foreign key with
``update_fields``, needs no batch for this: such a save locks the parent first.

It only locks parents that are API resources. When a child refers to a row that
isn't one, but whose saves change the ETags of resources, lock that row first
yourself, as an update of it would:

.. code-block:: python

    with transaction.atomic():
        EnkelvoudigInformatieObjectCanonical.objects.select_for_update(
            no_key=True
        ).get(pk=canonical.pk)
        Gebruiksrechten.objects.create(informatieobject=canonical, ...)

This library's exception handler,
:func:`~vng_api_common.exception_handling.exception_handler`, answers a cancelled
request with a 503 and ``Retry-After: 1``, so the client knows to try again.

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

Migration ``0008`` creates the ``StoredETag`` table. The first ``GET`` of a
resource after the upgrade calculates its ETag.

:class:`~vng_api_common.caching.ETagMixin` is deprecated: new models don't need it.
Its ``_etag`` column is no longer maintained. Drop it from your models with the
migration ``makemigrations`` writes.


Public API
==========

.. automodule:: vng_api_common.caching
    :members:


.. _ETag on MDN: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/ETag
