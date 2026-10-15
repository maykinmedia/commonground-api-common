"""
Invalidate stored ETags inside the transaction that writes.

Every receiver invalidates the resources :func:`~.registry.affected` returns,
before and after the write, so a moved or deleted row invalidates its old parents
too. Before a save or delete of an existing row, the row is locked first: another
transaction can't move it between reading its old parents and writing it.

``QuerySet.update``, ``bulk_create``, ``bulk_update`` and raw SQL send no signals and
are not covered.
"""

from collections.abc import Collection, Iterable
from enum import StrEnum

from django.db import DEFAULT_DB_ALIAS, models, transaction
from django.db.models.signals import (
    m2m_changed,
    post_delete,
    post_save,
    pre_delete,
    pre_save,
)
from django.dispatch import receiver

from .registry import DEPENDENCY_REGISTRY, affected, is_resource
from .store import Resource, forget, invalidate


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


def _only_etag(update_fields: object) -> bool:
    """
    Whether a save writes ``_etag`` alone, as ``ETagMixin.calculate_etag_value``
    does: nothing a representation reads.
    """
    return isinstance(update_fields, Collection) and set(update_fields) == {"_etag"}


def _lock(instance: models.Model, using: object) -> None:
    """
    Lock the row, so that reading its old parents and writing it can't interleave
    with another transaction moving it.

    A save outside a transaction (autocommit) can't lock; its single statement is
    all there is to interleave with.
    """
    alias = using if isinstance(using, str) else DEFAULT_DB_ALIAS
    if not transaction.get_connection(alias).in_atomic_block:
        return
    rows = (
        type(instance)
        ._base_manager.using(alias)
        .select_for_update()
        .filter(pk=instance.pk)
    )
    list(rows)  # evaluate


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
    **kwargs: object,
) -> None:
    """
    Lock an existing row, in a transaction, and invalidate the resources that read it
    before the save.
    """
    if raw or not _matters(sender) or _only_etag(kwargs.get("update_fields")):
        return
    if instance._state.adding or instance.pk is None:
        return  # nothing reads a row that doesn't exist yet
    _lock(instance, kwargs.get("using"))
    invalidate(affected(instance))


@receiver(post_save)
def invalidate_after_save(
    sender: type[models.Model],
    instance: models.Model,
    raw: bool = False,
    **kwargs: object,
) -> None:
    """Invalidate the resources that read the row after the save."""
    if raw or not _matters(sender) or _only_etag(kwargs.get("update_fields")):
        return
    invalidate(affected(instance))


@receiver(pre_delete)
def invalidate_before_delete(
    sender: type[models.Model], instance: models.Model, **kwargs: object
) -> None:
    """
    Lock the row and invalidate the resources that read it, including those whose
    foreign keys the delete sets to null.
    """
    if not _matters(sender):
        return
    _lock(instance, kwargs.get("using"))
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
    pk_set: set[object] | None,
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
            others = _linked(instance, sender, bool(kwargs.get("reverse")))
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
