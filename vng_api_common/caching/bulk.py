"""
Writes that send no signals, and so leave ETags as they were: an update in bulk
that keeps them right, and invalidating by hand.
"""

from collections import defaultdict

from django.db import models, transaction

from .registry import (
    DEPENDENCY_REGISTRY,
    affected,
    before_save,
    is_resource,
    written_by,
)
from .store import Resource, invalidate, invalidate_all


def invalidating_update(queryset: models.QuerySet, /, **values: object) -> int:
    """
    ``queryset.update(**values)``, for rows that API resources show. A plain
    ``QuerySet.update`` leaves their ETags unchanged, so clients keep getting 304s
    for resources it changed. This changes them, as saves of the rows would.

    .. code-block:: python

        # instead of Zaak.objects.filter(pk=zaak.pk).update(archiefactiedatum=None)
        invalidating_update(Zaak.objects.filter(pk=zaak.pk), archiefactiedatum=None)

    Returns the number of rows updated.
    """
    # The rows are locked first, as a save of each would lock it, and only the
    # locked rows are updated. Before the update it invalidates what the rows leave
    # if it writes a link; after, the rows' own ETags and those of the resources
    # that show a column it writes.
    model = queryset.model
    written = written_by(model, values)
    dependencies = DEPENDENCY_REGISTRY.get(model, ())
    # no savepoint in an atomic block: if this fails, it can only roll back
    nested = transaction.get_connection(queryset.db).in_atomic_block
    with transaction.atomic(using=queryset.db, savepoint=not nested):
        # by pk, so a queryset with DISTINCT or GROUP BY can be locked too
        selected = model._base_manager.filter(pk__in=queryset.values("pk"))
        locked = selected.order_by("pk").select_for_update()
        pks = list(locked.values_list("pk", flat=True))
        if not pks:
            return 0
        before = before_save(model, written)
        invalidate(frozenset().union(*(d.resources_of(pks) for d in before)))
        count = queryset.filter(pk__in=pks).update(**values)
        own = {Resource(model, pk) for pk in pks} if is_resource(model) else set()
        reading = (d.resources_of(pks) for d in dependencies if d.reads(written))
        invalidate(frozenset(own).union(*reading))
    return count


def invalidate_etags(*objs: models.Model) -> None:
    """
    Give new ETags to the resources that show ``objs``: their own, and those of
    every resource that lists or links them. Call it after writes that send no
    signals, so clients don't get 304s for what they changed.

    .. code-block:: python

        zios = ZaakInformatieObject.objects.bulk_create(
            [ZaakInformatieObject(zaak=zaak, informatieobject=url) for url in urls]
        )
        invalidate_etags(*zios)

    It changes the ETags of the resources that show the objects as they are now.
    So when a ``bulk_update`` changes a ``ForeignKey``, call it before as well,
    for the objects' old parents:

    .. code-block:: python

        with transaction.atomic():
            invalidate_etags(*zios)  # their old zaken
            for zio in zios:
                zio.zaak = other_zaak
            ZaakInformatieObject.objects.bulk_update(zios, ["zaak"])
            invalidate_etags(*zios)  # their new zaak

    Call it in the same transaction as the writes, so no client sees their data
    under an old ETag.
    """
    # Lock the rows first, as a save does, so no other transaction moves them
    # between reading their parents and the write that follows.
    by_model: defaultdict[type[models.Model], list[models.Model]] = defaultdict(list)
    for obj in objs:
        by_model[type(obj)].append(obj)
    if transaction.get_connection().in_atomic_block:
        for model, instances in by_model.items():
            rows = model._base_manager.filter(pk__in=[obj.pk for obj in instances])
            list(rows.order_by("pk").select_for_update().values_list("pk"))
    invalidate(frozenset().union(*map(affected, objs)))


def invalidate_all_etags(*resource_models: type[models.Model]) -> None:
    """
    Give new ETags to every resource, or to every resource of ``resource_models``.
    For writes whose reach you can't name, such as raw SQL; every resource it
    covers is calculated again on its next ``GET``.

    .. code-block:: python

        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("UPDATE zaken_zaak SET archiefstatus = 'gearchiveerd' ...")
            invalidate_all_etags(Zaak)

    It is one ``UPDATE`` of every stored ETag it covers, and it holds their row
    locks until the transaction commits: on large tables, keep that transaction
    short. Pass the models of the API resources that show what the SQL wrote, not
    the tables it wrote.
    """
    invalidate_all(resource_models)
