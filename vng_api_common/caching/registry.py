"""
Which resources read which rows, and which of their columns.

``conditional_retrieve`` registers each resource model with its serializer, and a
:class:`Dependency` for every relation the serializer reads, with the columns of
the rows it reaches that link them and that it shows. A write to a row affects
the resources returned by :func:`affected`, before and after the write; a save
that writes only some columns affects fewer.

.. code-block:: python

    @conditional_retrieve(extra_depends_on={"sheets"})
    class FolderViewSet(viewsets.ReadOnlyModelViewSet):
        serializer_class = FolderSerializer  # url, sheets (hyperlinks), tags, ...

    @conditional_retrieve()
    class SheetViewSet(viewsets.ReadOnlyModelViewSet):
        serializer_class = SheetSerializer  # url, folder (hyperlink), folder_code

    DEPENDENCY_REGISTRY[Sheet] == {
        Dependency(Folder, "sheets", frozenset({"folder"}), ALL, parent="folder_id")
    }
    DEPENDENCY_REGISTRY[Folder] == {
        Dependency(Sheet, "folder", frozenset(), frozenset({"code"})), ...
    }
    affected(sheet) == {Resource(Sheet, sheet.pk), Resource(Folder, sheet.folder_id)}
"""

from collections.abc import (
    Collection,
    Hashable,
    Iterable,
    Iterator,
    Sequence,
    Set as AbstractSet,
)
from dataclasses import dataclass, replace
from typing import Final, Literal, final

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models.fields.reverse_related import ForeignObjectRel

import structlog
from rest_framework.generics import GenericAPIView
from rest_framework.relations import (
    HyperlinkedIdentityField,
    HyperlinkedRelatedField,
    ManyRelatedField,
    PrimaryKeyRelatedField,
    RelatedField,
    SlugRelatedField,
)
from rest_framework.schemas.generators import BaseSchemaGenerator
from rest_framework.serializers import Field, ListSerializer, Serializer

from ..serializers import CacheMixin, GegevensGroepSerializer
from .store import Resource

logger = structlog.stdlib.get_logger(__name__)

MODEL_SERIALIZERS: dict[type[models.Model], type[Serializer]] = {}
"""The serializer of each resource model, which its ETag is calculated with."""

DEPENDENCY_REGISTRY: dict[type[models.Model], set["Dependency"]] = {}
"""The dependencies on each model, by that model: the source of the dependency."""


@final
class All:
    """
    Every column of a model, as :data:`ALL`: what may be read, or written, when
    which columns can't be told. It contains every name, and its union with any
    columns is itself.

    Not a ``frozenset``: their methods would take it for the empty set it holds.
    """

    __slots__ = ()

    def __contains__(self, name: object, /) -> Literal[True]:
        return True

    def __or__(self, other: "Columns", /) -> "All":
        return self

    __ror__ = __or__

    def __eq__(self, other: object, /) -> bool:
        return isinstance(other, All)

    def __hash__(self) -> int:
        return hash(All)

    def __repr__(self) -> str:
        return "ALL"


ALL: Final = All()

type Columns = frozenset[str] | All
"""Names of a model's fields, or :data:`ALL` of them."""


def overlap(a: Columns, b: Columns) -> bool:
    """Whether ``a`` and ``b`` have a column in common."""
    if isinstance(a, All):
        return bool(b)  # all of them, unless ``b`` is empty
    if isinstance(b, All):
        return bool(a)
    return not a.isdisjoint(b)


@dataclass(frozen=True)
class Dependency:
    """
    A resource model whose representation reads rows of another model, its source.

    :param resource: the resource model
    :param lookup: the ORM lookup from ``resource`` to the source, such as
      ``"sheets"`` or, through a nested serializer, ``"sheets__tags"``
    :param membership: the source's columns that decide which resources reach a
      row: ``{"folder"}`` of a sheet for ``"sheets"``
    :param shown: the source's columns the representation shows
    :param parent: the attname of the source's foreign key to the one resource
      that reaches a row, if the lookup is that key in reverse: ``"folder_id"``
    :param enforced: whether the database lets a row link to a source row only
      once it exists, as a foreign key constraint does
    """

    resource: type[models.Model]
    lookup: str
    membership: Columns = ALL
    shown: Columns = ALL
    parent: str | None = None
    enforced: bool = True

    def moves(self, written: Columns) -> bool:
        """
        Whether a save writing ``written`` of a row may change which resources
        reach it.
        """
        return overlap(written, self.membership)

    def reads(self, written: Columns) -> bool:
        """
        Whether a save writing ``written`` of a row may change the representation
        of a resource that reaches it, or which resources do.
        """
        return overlap(written, self.membership | self.shown)

    def resources(self, source: models.Model) -> frozenset[Resource]:
        """The resources that reach ``source`` through the lookup, in the database."""
        pks = self.resource._base_manager.filter(
            **{f"{self.lookup}__pk": source.pk}
        ).values_list("pk", flat=True)
        return frozenset(Resource(self.resource, pk) for pk in pks)

    def parent_of(self, source: models.Model, written: Columns) -> frozenset[Resource]:
        """
        After a save of ``source`` that wrote its ``parent`` key, among
        ``written``: the resource that reaches it, read off ``source``. Otherwise,
        those in the database.
        """
        if self.parent is None or (
            type(source)._meta.get_field(self.parent).name not in written
        ):
            return self.resources(source)
        pk = getattr(source, self.parent)
        return frozenset() if pk is None else frozenset({Resource(self.resource, pk)})

    def resources_of(self, pks: Collection[Hashable]) -> frozenset[Resource]:
        """The resources that reach any of the source's rows with ``pks``."""
        rows = self.resource._base_manager.filter(**{f"{self.lookup}__pk__in": pks})
        return frozenset(
            Resource(self.resource, pk)
            for pk in rows.values_list("pk", flat=True).distinct()
        )

    def merge(self, other: "Dependency") -> "Dependency":
        """This dependency, reading what ``other``, of the same lookup, reads too."""
        return replace(
            self,
            membership=self.membership | other.membership,
            shown=self.shown | other.shown,
            enforced=self.enforced and other.enforced,
        )


type Edge = tuple[type[models.Model], Dependency]
"""A dependency, with its source model: the key it is registered under."""


@dataclass(frozen=True)
class _Hop:
    """
    A step along a relation, from a model to its ``target``.

    :param near: the columns of the model stepped from that link it to the target
    :param far: the columns of the target that link it to the model stepped from
    :param parent: the attname of the target's foreign key, if ``far`` is that key
      and it holds the pk of the model stepped from
    :param enforced: whether the database lets a row link to a target row only once
      it exists
    """

    query_name: str
    target: type[models.Model]
    near: Columns
    far: Columns
    parent: str | None = None
    enforced: bool = True


def _hop(field: models.Field | ForeignObjectRel) -> _Hop | None:
    """The step along ``field``; ``None`` if it is not a relation."""
    target = field.related_model
    if not field.is_relation or not isinstance(target, type):
        return None
    if field.many_to_many:  # linked in a table of its own
        m2m = field.field if isinstance(field, ForeignObjectRel) else field
        link = m2m.remote_field
        # a through model of its own may be written without m2m_changed
        enforced = (
            isinstance(link, models.ManyToManyRel)
            and link.through is not None
            and bool(link.through._meta.auto_created)
            and link.db_constraint
        )
        return _Hop(field.name, target, frozenset(), frozenset(), enforced=enforced)
    if isinstance(field, ForeignObjectRel):  # a foreign key of the target, reversed
        key = field.field
        if not key.concrete:
            return _Hop(field.name, target, ALL, ALL)
        parent = key.attname if key.target_field is field.model._meta.pk else None
        return _Hop(field.name, target, frozenset(), frozenset({key.name}), parent)
    if field.concrete:  # a foreign key
        # django-stubs lacks ForeignKey.db_constraint
        enforced = bool(getattr(field, "db_constraint", False))
        return _Hop(
            field.name, target, frozenset({field.name}), frozenset(), enforced=enforced
        )
    return _Hop(field.name, target, ALL, ALL)  # such as a GenericRelation


def _relation(model: type[models.Model], name: str) -> _Hop | None:
    """
    The step along the relation that the attribute or accessor ``name`` of
    ``model`` reads; ``None`` if it is not a relation.

    ``"sheet_set"`` of a folder steps to ``Sheet`` with query name ``"sheet"``, as
    ``Folder.objects.filter(sheet=...)`` has it.
    """
    for field in model._meta.get_fields():
        accessor = (
            field.get_accessor_name()
            if isinstance(field, ForeignObjectRel)
            else field.name
        )
        if accessor == name:
            return _hop(field)
    return None


def _column(model: type[models.Model], name: str) -> Columns:
    """
    The column the attribute ``name`` of ``model`` reads: nothing for the primary
    key, which a save can't change; :data:`ALL` if it is no column.
    """
    try:
        field = model._meta.get_field(name)
    except FieldDoesNotExist:
        return frozenset() if name == "pk" else ALL
    if isinstance(field, ForeignObjectRel | models.GeneratedField):
        return ALL  # a GeneratedField reads the columns it is generated from
    if not field.concrete:
        return ALL
    return frozenset() if field.primary_key else frozenset({field.name})


def _listed(model: type[models.Model]) -> Columns:
    """
    The columns of ``model`` that decide which of its rows a list shows, and in what
    order: those of ``Meta.ordering``. :data:`ALL` if anything else may, such as
    a default manager's own queryset, or the database's order without one.
    """
    manager = type(model._default_manager)
    if manager.get_queryset is not models.Manager.get_queryset:
        return ALL
    ordering = model._meta.ordering
    if not ordering:
        return ALL
    columns: Columns = frozenset()
    for name in ordering:
        if isinstance(name, str) and "__" not in name and name != "?":
            columns |= _column(model, name.removeprefix("-"))
        else:  # an expression, a relation's column, or random
            columns = ALL
    return columns


# the URLs these build read the lookup attribute alone
_URL_BUILDERS = frozenset({HyperlinkedRelatedField.get_url, CacheMixin.get_url})


def _shown_by(field: Field, model: type[models.Model]) -> Columns:
    """The columns of each row of ``model`` that the related ``field`` shows."""
    match field:
        case ManyRelatedField() if field.child_relation is not None:
            return _shown_by(field.child_relation, model) | _listed(model)
        case PrimaryKeyRelatedField() if (
            type(field).to_representation is PrimaryKeyRelatedField.to_representation
            and field.pk_field is None
        ):
            return frozenset()
        case SlugRelatedField() if (
            type(field).to_representation is SlugRelatedField.to_representation
        ):
            return _column(model, field.slug_field)
        case HyperlinkedRelatedField() if (
            type(field).get_url in _URL_BUILDERS
            and type(field).to_representation
            is HyperlinkedRelatedField.to_representation
        ):
            return _column(model, field.lookup_field) | _column(
                model, field.lookup_url_kwarg
            )
    return ALL


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
        nested: Field = (
            field.child
            if isinstance(field, ListSerializer) and field.child is not None
            else field
        )

        hops: list[tuple[_Hop, str]] = []
        reached, lookup = model, prefix
        for name in field.source_attrs:
            if (hop := _relation(reached, name)) is None:
                break
            reached = hop.target
            lookup = f"{lookup}__{hop.query_name}" if lookup else hop.query_name
            hops.append((hop, lookup))
        rest = field.source_attrs[len(hops) :]

        for i, (hop, hop_lookup) in enumerate(hops):
            following = hops[i + 1][0] if i + 1 < len(hops) else None
            yield (
                hop.target,
                Dependency(
                    resource,
                    hop_lookup,
                    membership=hop.far
                    | (frozenset() if following is None else following.near),
                    # a row passed through shows nothing but its links
                    shown=frozenset()
                    if following is not None
                    else _shown(nested, hop.target, rest),
                    parent=hop.parent if i == 0 and not prefix else None,
                    enforced=hop.enforced,
                ),
            )

        if isinstance(nested, RelatedField | ManyRelatedField) and rest:
            logger.warning(
                "related_source_not_a_relation",
                resource=resource.__name__,
                source=field.source,
                attribute=rest[0],
                hint="declare the relations it reads in extra_depends_on",
            )
        if not isinstance(nested, Serializer):
            continue
        if not rest:  # ``source="*"`` reads the same row
            yield from _edges(resource, reached, lookup, nested)
        elif isinstance(nested, GegevensGroepSerializer) and len(rest) == 1:
            # a group of the columns of the row reached, a ``GegevensGroepType``
            yield from _edges(resource, reached, lookup, nested)
        else:
            # it reads rows through something other than a relation, such as a
            # property: which rows can't be introspected
            logger.warning(
                "nested_source_not_a_relation",
                resource=resource.__name__,
                source=field.source,
                attribute=rest[0],
                hint="declare the relations it reads in extra_depends_on",
            )


def _shown(field: Field, model: type[models.Model], rest: Sequence[str]) -> Columns:
    """
    The columns of the row of ``model`` that ``field`` reaches last that it shows,
    reading the attributes ``rest`` of it.
    """
    if isinstance(field, Serializer):
        return ALL
    if isinstance(field, RelatedField | ManyRelatedField):
        return ALL if rest else _shown_by(field, model)
    if len(rest) == 1:  # ``source="folder.code"``
        return _column(model, rest[0])
    return ALL


def _register(source: type[models.Model], dependency: Dependency) -> None:
    """Add ``dependency``, merged with a registered one of the same lookup."""
    registered = DEPENDENCY_REGISTRY.setdefault(source, set())
    for other in registered:
        if (other.resource, other.lookup) == (dependency.resource, dependency.lookup):
            registered.discard(other)
            dependency = other.merge(dependency)
            break
    registered.add(dependency)


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
        if (hop := _hop(names[name])) is not None:
            # read as a ``SerializerMethodField`` pleases: any column
            dependency = Dependency(model, name, hop.far, ALL, hop.parent, hop.enforced)
            edges.append((hop.target, dependency))
    for source, dependency in edges:
        _register(source, dependency)


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


def written_by(
    model: type[models.Model], update_fields: Iterable[str] | None
) -> Columns:
    """
    The fields a save with ``update_fields`` writes, by name, also when given by
    attname: ``{"folder"}`` for ``["folder_id"]``. :data:`ALL` without them.
    """
    if update_fields is None:
        return ALL
    return frozenset(model._meta.get_field(name).name for name in update_fields)


def before_save(model: type[models.Model], written: Columns) -> tuple[Dependency, ...]:
    """
    The dependencies on ``model`` that a save writing ``written`` has to lock the
    row for, ``FOR UPDATE``, and invalidate before it writes.

    Those through which it may move the row, whose old resources it reads under
    the lock. And those whose resources read what it writes, unless the row's own
    ``parent`` key decides them: other rows decide which resources reach this one,
    and another transaction may change them meanwhile. Linking a row to this one
    locks it ``FOR KEY SHARE``, which ``FOR UPDATE`` waits for, and the update of a
    save, ``FOR NO KEY UPDATE``, doesn't. Further along a lookup, invalidating
    waits for a transaction that invalidated the same resources while moving rows.
    """
    return tuple(
        d
        for d in DEPENDENCY_REGISTRY.get(model, ())
        if d.moves(written) or (d.reads(written) and d.parent is None)
    )


def affected_by_save(
    instance: models.Model, written: Columns, created: bool
) -> frozenset[Resource]:
    """
    After a save of ``instance`` that wrote ``written``: the resources whose
    representation it may have changed, as the database holds them now.

    A dependency whose ``parent`` key the save wrote reads it off ``instance``,
    which holds what the database does.

    A new row is reached only through its own columns, or through a link the
    database doesn't enforce: a row that links to it otherwise was inserted earlier
    in this transaction, and invalidated what reaches that row.
    """
    model = type(instance)
    own = {Resource(model, instance.pk)} if is_resource(model) else set()
    dependent = (
        dependency.parent_of(instance, ALL if created else written)
        for dependency in DEPENDENCY_REGISTRY.get(model, ())
        if (
            dependency.membership != frozenset() or not dependency.enforced
            if created
            else dependency.reads(written)
        )
    )
    return frozenset(own.union(*dependent))
