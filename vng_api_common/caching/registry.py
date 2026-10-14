"""
Which resources read which rows.

``conditional_retrieve`` registers each resource model with its serializer, and a
:class:`Dependency` for every relation the serializer reads. A write to a row then
affects the resources returned by :func:`affected`, before and after the write.

.. code-block:: python

    @conditional_retrieve(extra_depends_on={"sheets"})
    class FolderViewSet(viewsets.ReadOnlyModelViewSet):
        serializer_class = FolderSerializer  # url, sheets, tags, attachments (nested)

    DEPENDENCY_REGISTRY[Sheet] == {Dependency(Folder, "sheets")}
    DEPENDENCY_REGISTRY[Tag] == {Dependency(Folder, "tags")}
    DEPENDENCY_REGISTRY[Attachment] == {Dependency(Folder, "attachments")}
    affected(sheet) == {Resource(Sheet, sheet.pk), Resource(Folder, sheet.folder_id)}
"""

from collections.abc import Iterator, Set as AbstractSet
from dataclasses import dataclass

from django.db import models
from django.db.models.fields.reverse_related import ForeignObjectRel

import structlog
from rest_framework.generics import GenericAPIView
from rest_framework.relations import HyperlinkedIdentityField
from rest_framework.schemas.generators import BaseSchemaGenerator
from rest_framework.serializers import ListSerializer, Serializer

from .store import Resource

logger = structlog.stdlib.get_logger(__name__)

MODEL_SERIALIZERS: dict[type[models.Model], type[Serializer]] = {}
"""The serializer of each resource model, which its ETag is calculated with."""

DEPENDENCY_REGISTRY: dict[type[models.Model], set["Dependency"]] = {}
"""The dependencies on each model, by that model: the source of the dependency."""


@dataclass(frozen=True)
class Dependency:
    """
    A resource model whose representation reads rows of another model, its source.

    :param resource: the resource model
    :param lookup: the ORM lookup from ``resource`` to the source, such as
      ``"sheets"`` or, through a nested serializer, ``"sheets__tags"``
    """

    resource: type[models.Model]
    lookup: str

    def resources(self, source: models.Model) -> frozenset[Resource]:
        """The resources that reach ``source`` through the lookup."""
        pks = self.resource._base_manager.filter(
            **{self.lookup: source.pk}
        ).values_list("pk", flat=True)
        return frozenset(Resource(self.resource, pk) for pk in pks)


type Edge = tuple[type[models.Model], Dependency]
"""A dependency, with its source model: the key it is registered under."""


def _relation(
    model: type[models.Model], name: str
) -> tuple[str, type[models.Model]] | None:
    """
    The ORM query name and the target model of the relation that the attribute or
    accessor ``name`` of ``model`` reads; ``None`` if it is not a relation.

    ``"sheet_set"`` of a folder is ``("sheet", Sheet)``, as ``Folder.objects.filter(
    sheet=...)`` has it.
    """
    for field in model._meta.get_fields():
        target = field.related_model
        if not field.is_relation or not isinstance(target, type):
            continue
        accessor = (
            field.get_accessor_name()
            if isinstance(field, ForeignObjectRel)
            else field.name
        )
        if accessor == name:
            return field.name, target
    return None


def _edges(
    resource: type[models.Model],
    model: type[models.Model],
    prefix: str,
    serializer: Serializer,
) -> Iterator[Edge]:
    """
    The dependencies of ``resource`` that ``serializer`` reads, which serializes
    rows of ``model`` found at ``prefix`` from ``resource``.

    A field reaches a relation through each attribute of its source, so
    ``source="folder.owner"`` reads the folder and its owner.
    """
    for field in serializer.fields.values():
        if isinstance(field, HyperlinkedIdentityField):
            continue  # the resource itself
        nested = field.child if isinstance(field, ListSerializer) else field

        reached, lookup, resolved = model, prefix, True
        for name in field.source_attrs:
            relation = _relation(reached, name)
            if relation is None:
                resolved = False
                break
            query_name, reached = relation
            lookup = f"{lookup}__{query_name}" if lookup else query_name
            yield reached, Dependency(resource, lookup)

        if not isinstance(nested, Serializer):
            continue
        if resolved:  # ``source="*"`` reads the same row
            yield from _edges(resource, reached, lookup, nested)
        elif len(field.source_attrs) == 1:
            # a group of this row's columns, such as a ``GegevensGroepType``
            yield from _edges(resource, model, prefix, nested)


def extract_dependencies(
    viewset: type[GenericAPIView], explicit_field_names: AbstractSet[str]
) -> None:
    """
    Register the viewset's model with its serializer, and a dependency for every
    relation the serializer reads.

    Related fields, hyperlinked or not, and nested serializers count; a nested
    serializer's own relations count too, with their lookups chained to its own.
    The model fields named in ``explicit_field_names`` count as well: what a
    ``SerializerMethodField`` reads can't be introspected.
    """
    model = viewset.queryset.model  # type: ignore[attr-defined]

    names = {field.name: field for field in model._meta.get_fields()}
    if unknown := {name for name in explicit_field_names if name not in names}:
        raise ValueError(
            f"The field names {', '.join(sorted(unknown))} could not be found on "
            f"the model {model}"
        )

    # a viewset, whose ``as_view`` takes the actions; ``GenericAPIView``'s doesn't
    callback = viewset.as_view({"get": "retrieve"})  # pyright: ignore[reportCallIssue]
    view = BaseSchemaGenerator().create_view(callback, method="GET", request=None)
    serializer = view.get_serializer()

    if model in MODEL_SERIALIZERS:
        logger.warning("model_already_registered", model=model.__name__)
    else:
        MODEL_SERIALIZERS[model] = type(serializer)

    edges = list(_edges(model, model, "", serializer))
    for name in explicit_field_names:
        if isinstance(source := names[name].related_model, type):
            edges.append((source, Dependency(model, name)))
    for source, dependency in edges:
        DEPENDENCY_REGISTRY.setdefault(source, set()).add(dependency)


def is_resource(model: type[models.Model]) -> bool:
    """Whether ``model`` is registered as a resource."""
    return model in MODEL_SERIALIZERS


def affected(instance: models.Model) -> frozenset[Resource]:
    """
    The resources whose representation reads ``instance``, as the database holds
    them now: ``instance`` itself if it is a resource, and those reaching it through
    a dependency.

    A write affects the union of this before and after the write.
    """
    model = type(instance)
    own = {Resource(model, instance.pk)} if is_resource(model) else set()
    dependent = (
        dependency.resources(instance)
        for dependency in DEPENDENCY_REGISTRY.get(model, ())
    )
    return frozenset(own.union(*dependent))
