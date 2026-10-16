"""
Invalidate stored ETags inside the transaction that writes.

Every receiver invalidates the resources :func:`~.registry.affected` returns,
before and after the write, so a moved or deleted row invalidates its old parents
too. Before a delete the row is locked first: another transaction can't move it
between reading its old parents and writing it.

A save narrows that to the columns it writes (``update_fields``), see
:func:`~.registry.before_save` and :func:`~.registry.affected_by_save`.

Write in a transaction. A save in autocommit can't lock, and each statement
commits on its own, so a GET between them may store an ETag that the rest of the
save makes stale; invalidating again after the save narrows that window.

``QuerySet.update`` sends no signals: use :func:`~.bulk.invalidating_update`.
``bulk_create``, ``bulk_update`` and raw SQL are not covered.
"""

from collections.abc import Hashable, Iterable, Set as AbstractSet
from enum import StrEnum

from django.db import DEFAULT_DB_ALIAS, IntegrityError, models, transaction
from django.db.models.signals import (
    m2m_changed,
    post_delete,
    post_save,
    pre_delete,
    pre_save,
)
from django.dispatch import receiver

from .registry import (
    DEPENDENCY_REGISTRY,
    affected,
    affected_by_save,
    before_save,
    is_resource,
    written_by,
)
from .store import Resource, forget, invalidate

# what a save invalidated before it wrote, for its post_save to invalidate again
_BEFORE = "_etags_invalidated_before_save"
# that a save found no row to lock, so it inserts
_ABSENT = "_etags_found_no_row"


class M2MAction(StrEnum):
    """The ``action`` of ``m2m_changed``."""

    PRE_ADD = "pre_add"
    POST_ADD = "post_add"
    PRE_REMOVE = "pre_remove"
    POST_REMOVE = "post_remove"
    PRE_CLEAR = "pre_clear"
    POST_CLEAR = "post_clear"


def _matters(model: type[models.Model]) -> bool:
    """Whether a write to ``model`` can affect a resource."""
    return is_resource(model) or model in DEPENDENCY_REGISTRY


def _only_etag(update_fields: AbstractSet[str] | None) -> bool:
    """
    Whether a save writes ``_etag`` alone, as ``ETagMixin.calculate_etag_value``
    does: nothing a representation reads.
    """
    return update_fields == {"_etag"}


def _lock(instance: models.Model, using: str) -> bool:
    """
    Lock the row, so that reading its old parents and writing it can't interleave
    with another transaction moving it. Whether the row may exist.

    A save outside a transaction (autocommit) can't lock, so the row may exist;
    the lookups of an insert find nothing.
    """
    if not transaction.get_connection(using).in_atomic_block:
        return True
    rows = type(instance)._base_manager.using(using).filter(pk=instance.pk)
    return bool(list(rows.select_for_update()))


def _linked(
    instance: models.Model, sender: type[models.Model], reverse: bool
) -> models.QuerySet:
    """
    The rows linked to ``instance`` through the many-to-many whose through model is
    ``sender``, for ``reverse`` as ``m2m_changed`` has it.
    """
    for relation in type(instance)._meta.get_fields():
        if reverse and isinstance(relation, models.ManyToManyRel):
            field, other = relation.field, relation.field.model
            to_instance, to_other = (
                field.m2m_reverse_field_name(),
                field.m2m_field_name(),
            )
        elif not reverse and isinstance(relation, models.ManyToManyField):
            field, other = relation, relation.related_model
            to_instance, to_other = (
                field.m2m_field_name(),
                field.m2m_reverse_field_name(),
            )
        else:
            continue
        if field.remote_field.through is sender:
            links = sender._base_manager.filter(**{to_instance: instance.pk})
            return other._base_manager.filter(pk__in=links.values_list(to_other))
    return type(instance)._base_manager.none()


@receiver(pre_save)
def invalidate_before_save(
    sender: type[models.Model],
    instance: models.Model,
    raw: bool = False,
    using: str = DEFAULT_DB_ALIAS,
    update_fields: AbstractSet[str] | None = None,
    **kwargs: object,
) -> None:
    """
    Before a save of a row that may exist, lock it, in a transaction, and
    invalidate the resources :func:`~.registry.before_save` names.
    """
    if raw or not _matters(sender) or _only_etag(update_fields):
        return
    pk = sender._meta.pk
    if instance.pk is None or (
        instance._state.adding and (pk.has_default() or pk.has_db_default())
    ):
        return  # an insert: nothing reads a row that doesn't exist yet
    if not (dependencies := before_save(sender, written_by(sender, update_fields))):
        return
    if not _lock(instance, using):
        vars(instance)[_ABSENT] = True  # an insert, with a pk of its own
        return
    resources = frozenset().union(*(d.resources(instance) for d in dependencies))
    invalidate(resources)
    vars(instance)[_BEFORE] = resources


@receiver(post_save)
def invalidate_after_save(
    sender: type[models.Model],
    instance: models.Model,
    created: bool = False,
    raw: bool = False,
    update_fields: AbstractSet[str] | None = None,
    **kwargs: object,
) -> None:
    """
    Invalidate the resources whose representations the save may have changed, and
    again those it invalidated before it wrote.
    """
    if raw or not _matters(sender) or _only_etag(update_fields):
        return
    if vars(instance).pop(_ABSENT, False) and not created:
        # another transaction inserted the row meanwhile, and this save overwrote
        # it: what that row was linked to before is unknown
        raise IntegrityError(
            f"{sender.__name__} {instance.pk} was inserted by another transaction "
            "while this save inserted it"
        )
    written = written_by(sender, update_fields)
    before: frozenset[Resource] = vars(instance).pop(_BEFORE, frozenset())
    after = affected_by_save(instance, written, created)
    invalidate(before | after)


@receiver(pre_delete)
def invalidate_before_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str = DEFAULT_DB_ALIAS,
    **kwargs: object,
) -> None:
    """
    Lock the row and invalidate the resources that read it, including those whose
    foreign keys the delete sets to null.
    """
    if not _matters(sender):
        return
    _lock(instance, using)
    invalidate(affected(instance))


@receiver(post_delete)
def forget_after_delete(
    sender: type[models.Model], instance: models.Model, **kwargs: object
) -> None:
    """Forget the stored ETag of a deleted resource."""
    if is_resource(sender):
        forget(Resource(sender, instance.pk))


@receiver(m2m_changed)
def invalidate_on_m2m_change(
    sender: type[models.Model],
    instance: models.Model,
    action: str,
    model: type[models.Model],
    pk_set: AbstractSet[Hashable] | None,
    reverse: bool = False,
    **kwargs: object,
) -> None:
    """
    Invalidate the resources that read either side of the changed links, before
    (``pre_*``) and after (``post_*``) the change. For ``clear`` the other side is
    whatever ``instance`` is linked to before the clear.
    """
    if not (_matters(type(instance)) or _matters(model)):
        return
    match M2MAction(action):
        case (
            M2MAction.PRE_ADD
            | M2MAction.PRE_REMOVE
            | M2MAction.POST_ADD
            | M2MAction.POST_REMOVE
        ):
            others: Iterable[models.Model] = model._base_manager.filter(
                pk__in=pk_set or ()
            )
        case M2MAction.PRE_CLEAR:
            others = _linked(instance, sender, reverse)
        case M2MAction.POST_CLEAR:
            others = ()
    invalidate(frozenset(affected(instance).union(*map(affected, others))))


def mark_related_instances_for_etag_update(
    sender: type[models.Model], instance: models.Model, **kwargs: object
) -> None:
    """
    Does nothing: the receiver before stored ETags, kept so that migrations which
    disconnect it while they run, such as Open Zaak's, still import.
    """
