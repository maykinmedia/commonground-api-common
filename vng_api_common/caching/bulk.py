"""
Updates in bulk that keep ETags right: see :func:`invalidating_update`.
"""

from django.db import models, transaction

from .registry import DEPENDENCY_REGISTRY, before_save, is_resource, written_by
from .store import Resource, invalidate


def invalidating_update(queryset: models.QuerySet, /, **values: object) -> int:
    """
    Update like ``queryset.update(**values)``, and give new ETags to the resources
    it changes, as saves of the rows would. A plain ``QuerySet.update`` leaves
    their ETags unchanged, so clients keep getting 304s for resources it changed.

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
