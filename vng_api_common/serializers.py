import inspect
import re
from collections import OrderedDict
from collections.abc import Callable, Iterable
from functools import reduce
from typing import TYPE_CHECKING, Any, cast

from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.db import models, transaction
from django.db.models import Model
from django.utils.translation import gettext_lazy as _

from dateutil.relativedelta import relativedelta
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import fields, serializers
from rest_framework.relations import (
    ObjectTypeError,
    ObjectValueError,
    RelatedField,
)
from rest_framework.request import Request
from rest_framework.utils.field_mapping import (
    get_nested_relation_kwargs,
    get_url_kwargs,
)
from rest_framework_nested.relations import NestedHyperlinkedRelatedField

from .choices import TextChoicesWithDescriptions
from .descriptors import GegevensGroepType
from .settings import get_setting
from .validators import URNValidator

if TYPE_CHECKING:
    from rest_framework.serializers import HyperlinkedRelatedField as _Base
else:
    _Base = object

if TYPE_CHECKING:
    from rest_framework.serializers import ModelSerializer as _BaseNested
else:
    _BaseNested = object

format_relativedelta: Callable[[relativedelta], str] | None
parse_relativedelta: Callable[[str], relativedelta] | None

try:
    # 1.1.x
    from relativedeltafield.utils import (
        format_relativedelta,
        parse_relativedelta,  # type: ignore[override]
    )
except ImportError:
    try:
        # 1.0.x
        from relativedeltafield import (
            format_relativedelta,  # type: ignore[attr-defined]
            parse_relativedelta,  # type: ignore[attr-defined]
        )
    except ImportError:
        format_relativedelta = None
        parse_relativedelta = None


def field_allows_empty_values(field: fields.Field) -> bool:
    return field.allow_null or getattr(field, "allow_blank", False)


@extend_schema_field(OpenApiTypes.DURATION)
class DurationField(fields.DurationField):
    def to_internal_value(self, value: object) -> Any:
        if isinstance(value, relativedelta):
            return value
        try:
            return parse_relativedelta(str(value))  # type: ignore[call-arg]
        except ValueError:
            self.fail("invalid", format="P(n)Y(n)M(n)D")

    def to_representation(self, value) -> str | None:
        if isinstance(value, relativedelta):
            return format_relativedelta(value)  # type: ignore[call-arg]
        return None


class FieldValidationErrorSerializer(serializers.Serializer):
    """
    Formaat van validatiefouten.
    """

    name = serializers.CharField(help_text="Naam van het veld met ongeldige gegevens")
    code = serializers.CharField(help_text="Systeemcode die het type fout aangeeft")
    reason = serializers.CharField(
        help_text="Uitleg wat er precies fout is met de gegevens"
    )


class FoutSerializer(serializers.Serializer):
    """
    Formaat van HTTP 4xx en 5xx fouten.
    """

    type = serializers.CharField(
        help_text="URI referentie naar het type fout, bedoeld voor developers",
        required=False,
        allow_blank=True,
    )
    # not according to DSO, but possible for programmatic checking
    code = serializers.CharField(help_text="Systeemcode die het type fout aangeeft")
    title = serializers.CharField(help_text="Generieke titel voor het type fout")
    status = serializers.IntegerField(help_text="De HTTP status code")
    detail = serializers.CharField(
        help_text="Extra informatie bij de fout, indien beschikbaar"
    )
    instance = serializers.CharField(
        help_text="URI met referentie naar dit specifiek voorkomen van de fout. Deze kan "
        "gebruikt worden in combinatie met server logs, bijvoorbeeld."
    )


class ValidatieFoutSerializer(FoutSerializer):
    invalid_params = FieldValidationErrorSerializer(many=True)


def add_choice_values_help_text(
    choices: type[models.Choices] | Iterable[tuple[str, str]],
) -> str:
    is_dj_choices = inspect.isclass(choices) and issubclass(choices, models.Choices)

    if is_dj_choices:
        _choices = choices.choices  # type: ignore[attr-defined]
        if issubclass(choices, TextChoicesWithDescriptions):  # type: ignore[attr-defined]
            descriptions = choices.descriptions()
            _choices = [
                (key, f"({value}) {descriptions[key]}") for key, value in _choices
            ]
    else:
        _choices = choices
    items = [f"* `{key}` - {value}" for key, value in _choices]  # type: ignore[attr-defined]

    return "Uitleg bij mogelijke waarden:\n\n" + "\n".join(items)


class GegevensGroepSerializerMetaclass(serializers.SerializerMetaclass):
    def __new__(cls, name, bases, attrs):
        Meta = attrs.get("Meta")
        if Meta:
            assert hasattr(Meta, "model"), (
                "The 'model' class must be defined on the Meta."
            )
            assert hasattr(Meta, "gegevensgroep"), (
                "The 'gegevensgroep' name must be defined on the Meta."
            )

            gegevensgroep = getattr(Meta.model, Meta.gegevensgroep)
            Meta.fields = []

            extra_kwargs = {}

            for field_name, model_field in gegevensgroep.mapping.items():
                Meta.fields.append(field_name)

                allow_blank = model_field.blank
                # For fields with choices, we do not allow empty strings unless the
                # field is marked as optional
                if model_field.choices:
                    allow_blank = field_name in gegevensgroep.optional

                default_extra_kwargs = {
                    "required": field_name not in gegevensgroep.optional,
                    "allow_null": False,
                    "allow_blank": allow_blank,
                }

                if model_field.name != field_name:
                    default_extra_kwargs["source"] = model_field.name

                internal_type = model_field.get_internal_type()
                if internal_type not in ["CharField", "TextField"]:
                    del default_extra_kwargs["allow_blank"]
                if internal_type == "BooleanField":
                    del default_extra_kwargs["allow_null"]

                extra_kwargs[field_name] = default_extra_kwargs

                declared_extra_kwargs = getattr(Meta, "extra_kwargs", {}).get(
                    field_name
                )
                if declared_extra_kwargs:
                    extra_kwargs[field_name].update(declared_extra_kwargs)

            Meta.extra_kwargs = extra_kwargs

        return super().__new__(cls, name, bases, attrs)


class GegevensGroepSerializer(
    serializers.ModelSerializer, metaclass=GegevensGroepSerializerMetaclass
):
    """
    Generate a serializer out of a GegevensGroepType.

    Usage::

        >>> class VerlengingSerializer(GegevensGroepSerializer):
        ...     class Meta:
        ...         model = Zaak
        ...         gegevensgroep = 'verlenging'
        >>>

    Where ``Zaak.verlenging`` is a :class:``GegevensGroepType``.
    """

    def validate_empty_values(
        self,
        data: object,
    ) -> Any:
        """
        Even if we're in partial-serializer mode, the full gegevensgroep
        _must_ be provided.
        """
        (is_empty_value, data) = super().validate_empty_values(data)

        if self.root.partial:
            if is_empty_value:
                return (is_empty_value, data)

            errors = OrderedDict()

            for field_name, field in self.fields.items():
                if field.required and field_name not in data:
                    try:
                        field.fail("required")
                    except serializers.ValidationError as exc:
                        errors[field_name] = exc.detail

            if errors:
                raise serializers.ValidationError(errors)

        return (is_empty_value, data)

    def to_representation(self, instance) -> dict[str, Any] | None:  # type: ignore[override]
        """
        Output the result of accessing the descriptor.
        """
        ret = OrderedDict()
        fields = self._readable_fields

        for field in fields:
            attribute = instance[field.field_name]
            if attribute is None:
                ret[field.field_name] = None
            else:
                ret[field.field_name] = field.to_representation(attribute)

        if self.allow_null:
            fields_disallow_empty = not all(
                field_allows_empty_values(field) for field in self.fields.values()
            )
            all_values_empty = all(v in ("", None) for v in ret.values())

            # If the gegevensgroep is empty, but there are fields that do not allow
            # empty values, the only way for the serialized object to be valid according
            # to the OAS is if the entire gegevensgroep is serialized as `null`
            if fields_disallow_empty and all_values_empty:
                return None

        return ret

    def to_internal_value(self, data: dict[str, object]) -> dict[str, object]:
        """
        Pass through the original keys instead of reverse-mapping the source attrs.
        """
        value = super().to_internal_value(data)
        ret = {}
        for name, field in self.fields.items():
            if field not in self._writable_fields:
                continue
            if field.source not in value:
                continue
            ret[name] = value[field.source]
        return ret


class NestedGegevensGroepMixin(_BaseNested):
    """
    Set gegevensgroepdata from validated nested data.

    Usage: include the mixin on the ModelSerializer that has gegevensgroepen.
    """

    def _is_gegevensgroep(self, name: str):
        meta = cast(Any, self).Meta
        model = meta.model
        attr = getattr(model, name)
        return isinstance(attr, GegevensGroepType)

    def create(self, validated_data):
        """
        Handle nested writes.
        """
        gegevensgroepen = {}
        for name in list(validated_data.keys()):
            if not self._is_gegevensgroep(name):
                continue

            gegevensgroepen[name] = validated_data.pop(name)

        # avoid a number of queries if there's no gegevensgroep actions to perform
        if not gegevensgroepen:
            return super().create(validated_data)

        with transaction.atomic():
            # perform the default create
            obj = super().create(validated_data)
            for name, gegevensgroepdata in gegevensgroepen.items():
                setattr(obj, name, gegevensgroepdata)
            obj.save()

        return obj

    def update(self, instance, validated_data):
        """
        Handle nested writes.
        """
        for name in list(validated_data.keys()):
            if not self._is_gegevensgroep(name):
                continue
            setattr(instance, name, validated_data.pop(name))
        return super().update(instance, validated_data)


def get_nested_fk_attribute(
    instance: object,
    relation_path: str,
) -> object:
    """
    Retrieves an attribute from a nested foreign key relation.

    Args:
    - instance: The model instance (e.g., Book).
    - relation_path: A string with the relation path, e.g., 'author__publisher__name'.

    Returns:
    - The value of the nested attribute or None if not found.
    """
    relations = relation_path.split("__")

    return reduce(
        lambda obj, attr: getattr(obj, attr, None) if obj else None, relations, instance
    )


class CacheMixin(_Base):
    """
    Mixin for Hyperlinked DRF fields to cache the base URI per view, to avoid
    having to recalculate this for each related object that has to be serialized

    This cache is stored on the field instance itself, so it's reset between requests
    """

    lookup_url_kwarg = ""  # Should be defined on `HyperlinkedRelatedField`
    identifier_placeholder = "id-placeholder"

    def get_extra_reverse_kwargs(self) -> dict[str, str]:
        """
        Hook to inject extra kwargs to be passed to `reverse()`
        """
        return {}

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)

        self._reverse_cache = {}

    def get_url(
        self, obj: Model, view_name: str, request: Request, format: str | None
    ) -> str | None:
        # Unsaved objects will not yet have a valid URL.
        if hasattr(obj, "pk") and obj.pk in (None, ""):
            return None

        base_url = self._reverse_cache.get(view_name)

        if base_url is None:
            # If not cached, compute and cache it for this request cycle
            try:
                # Insert placeholders for identifiers, these will be replaced by
                # real identifiers later on
                kwargs = {self.lookup_url_kwarg: self.identifier_placeholder}
                kwargs.update(self.get_extra_reverse_kwargs())

                base_url = self.reverse(
                    view_name, kwargs=kwargs, request=request, format=format
                )
                self._reverse_cache[view_name] = base_url
            except Exception as e:
                raise ValueError(f"Could not resolve reverse for {view_name}: {e}")

        url = base_url.replace(
            self.identifier_placeholder, str(getattr(obj, self.lookup_url_kwarg))
        )
        return url


class LengthHyperlinkedRelatedField(CacheMixin, serializers.HyperlinkedRelatedField):
    default_error_messages = {
        "max_length": _("Ensure this field has no more than {max_length} characters."),
        "min_length": _("Ensure this field has at least {min_length} characters."),
    }

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.min_length = cast(int, kwargs.pop("min_length", 1))
        self.max_length = cast(int, kwargs.pop("max_length", 1000))
        kwargs.setdefault("allow_null", not kwargs.get("required", True))

        super().__init__(*args, **kwargs)

    def to_internal_value(self, data):
        if self.max_length and len(data) > self.max_length:
            self.fail("max_length", max_length=self.max_length, length=len(data))

        if self.min_length and len(data) < self.min_length:
            self.fail("min_length", max_length=self.min_length, length=len(data))

        return super().to_internal_value(data)


class CachedHyperlinkedRelatedField(CacheMixin, serializers.HyperlinkedRelatedField):
    """
    Subclass of ``serializers.HyperlinkedRelatedField`` that applies caching in
    ``.get_url()`` to ``reverse()`` calls to improve serialization performance
    """


class CachedHyperlinkedIdentityField(CacheMixin, serializers.HyperlinkedIdentityField):
    """
    Subclass of ``serializers.HyperlinkedIdentityField`` that applies caching in
    ``.get_url()`` to ``reverse()`` calls to improve serialization performance
    """


class CachedNestedHyperlinkedRelatedField(CacheMixin, NestedHyperlinkedRelatedField):
    """
    Subclass of ``serializers.HyperlinkedIdentityField`` that applies caching in
    ``.get_url()`` to ``reverse()`` calls to improve serialization performance
    """

    def get_extra_reverse_kwargs(self) -> dict[str, str]:
        return self.parent_lookup_kwargs

    def get_url(
        self, obj: Model, view_name: str, request: Request, format: str | None
    ) -> str | None:
        url = super().get_url(obj, view_name, request, format)

        if not url:
            return None

        # Replace the placeholder from the cached base URI with the actual identifier
        for v in self.parent_lookup_kwargs.values():
            url = url.replace(v, str(get_nested_fk_attribute(obj, v)))
        return url


URNSchema = {
    "type": "string",
    "format": "urn",
    "example": "urn:namespace:component:resource:uuid",
}


class NoUrnMatch(Exception):
    pass


@extend_schema_field(URNSchema)
class URNRelatedField(RelatedField):
    """
    A DRF field for representing related objects as URNs.

    URN format: urn:<namespace>:<component>:<resource>:<lookup_value>

    - urn_namespace: required or derived from the settings default
    - urn_component: derived from the view
    - urn_resource: derived from the related model name
    - lookup_value: value used to lookup the object (e.g., UUID or pk)

    """

    URN_PATTERN = re.compile(
        r"urn:(?P<namespace>[^:]+):(?P<component>[^:]+):"
        r"(?P<resource>[^:]+):(?P<lookup_value>[^:]+)",
        re.IGNORECASE,
    )
    UUID_REGEX = (
        "([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})"
    )

    lookup_field = "pk"
    default_validators = [URNValidator()]

    view_name = None
    urn_namespace = None
    urn_component = None
    urn_resource = None

    default_error_messages = {
        "required": _("This field is required."),
        "no_match": _("Invalid URN - Could not match the expected pattern."),
        "incorrect_match": _("Invalid URN - Does not conform to the expected format."),
        "does_not_exist": _("Invalid URN - Corresponding object does not exist."),
        "incorrect_type": _(
            "Incorrect type. Expected a string representing a URN, received {data_type}."
        ),
    }

    def __init__(self, view_name=None, **kwargs):
        self.view_name = view_name
        self.lookup_field = kwargs.pop("lookup_field", self.lookup_field)

        self.urn_namespace = kwargs.pop("urn_namespace", self.urn_namespace)

        if self.urn_namespace is None:
            self.urn_namespace = get_setting("URN_NAMESPACE")
        if not self.urn_namespace:
            raise ImproperlyConfigured(
                "URNRelatedField requires a `urn_namespace` to be specified."
            )

        self.urn_component = kwargs.pop("urn_component", self.urn_component)
        self.urn_resource = kwargs.pop("urn_resource", self.urn_resource)

        super().__init__(**kwargs)

    def get_object(self, lookup_kwarg, value):
        """
        Return the object corresponding to a matched URN.
        """
        lookup_kwargs = {lookup_kwarg: value}
        queryset = self.get_queryset()
        try:
            return queryset.get(**lookup_kwargs)  # type: ignore
        except ValueError as e:
            raise ObjectValueError(str(e)) from e
        except TypeError as e:
            raise ObjectTypeError(str(e)) from e

    def get_urn_component(self):
        """
        Extract the `urn_component` name from the DRF request context.
        """
        error_msg = (
            "URNRelatedField could not determine the `urn_component`: "
            "request, resolver_match, or namespace is missing in serializer context."
        )
        try:
            component = self.context["request"].resolver_match.namespace
        except Exception:
            raise ImproperlyConfigured(error_msg)

        if not component:
            raise ImproperlyConfigured(error_msg)

        return component

    def get_urn_resource(self, obj=None):
        """
        Extract the `urn_resource` name from the related model or identity object.
        """
        error_msg = (
            "URNRelatedField could not determine the `urn_resource`: "
            "model not found on the view or serializer."
        )

        try:
            queryset = self.get_queryset()
            model = (
                type(obj)
                if obj is not None
                else queryset.model
                if queryset is not None
                else self.parent.Meta.model
            )
            resource = model._meta.model_name
        except Exception:
            raise ImproperlyConfigured(error_msg)

        if not resource:
            raise ImproperlyConfigured(error_msg)

        return resource

    def get_urn(self, obj):
        """
        Given an object, return the URN that links to the object.
        """

        if hasattr(obj, "pk") and obj.pk in (None, ""):
            return None

        if self.urn_component is None:
            self.urn_component = self.get_urn_component()

        if self.urn_resource is None:
            self.urn_resource = self.get_urn_resource(obj)

        value = getattr(obj, self.lookup_field, None)

        return (
            f"urn:{self.urn_namespace}:{self.urn_component}:{self.urn_resource}:{value}"
            if value is not None
            else None
        )

    def run_validation(self, data=serializers.empty):
        # Validate the URN string before resolving it to a model instance.
        is_empty, data = self.validate_empty_values(data)
        return data if is_empty else self.to_internal_value(data)

    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("incorrect_type", data_type=type(data).__name__)

        # "urn:" is case-insensitive (RFC 8141 section 3)
        if not data.lower().startswith("urn:"):
            self.fail("no_match")

        match = self.URN_PATTERN.fullmatch(data)
        if not match:
            self.fail("incorrect_match")

        component = self.urn_component or self.get_urn_component()
        resource = self.urn_resource or self.get_urn_resource()
        assert self.urn_namespace is not None

        # Check the namespace, component, and resource against the expected values.
        # If they don't match, raise an error.
        if (
            match["namespace"].lower() != self.urn_namespace.lower()
            or match["component"] != component
            or match["resource"] != resource
        ):
            self.fail("incorrect_match")

        lookup_value = match["lookup_value"]
        if self.lookup_field == "uuid" and not re.fullmatch(
            self.UUID_REGEX, lookup_value
        ):
            self.fail("incorrect_match")

        try:
            return self.get_object(self.lookup_field, lookup_value)
        except (ObjectDoesNotExist, ObjectValueError, ObjectTypeError):
            self.fail("does_not_exist")

    def to_representation(self, value):
        value = self.get_urn(value)

        if not value:
            raise ImproperlyConfigured(
                "Could not resolve URN for the object using the configured view. "
                "You may have failed to include the related model in your API, "
                "or incorrectly configured the `urn_component` or `urn_resource` for this field."
            )
        return value


class URNIdentityField(URNRelatedField):
    """
    A read-only field that exposes the object's URN identity.
    """

    def __init__(self, *args, **kwargs):
        kwargs["read_only"] = True
        kwargs["source"] = "*"
        super().__init__(*args, **kwargs)

    def use_pk_only_optimization(self):
        return False


class URNModelSerializer(serializers.ModelSerializer):
    serializer_related_field = URNRelatedField
    urn_field_name = "urn"

    def get_default_field_names(self, declared_fields, model_info):
        """
        Return the default list of field names that will be used if the
        `Meta.fields` option is not specified.
        """
        return (
            [self.urn_field_name]
            + list(declared_fields)
            + list(model_info.fields)
            + list(model_info.forward_relations)
        )

    def build_urn_field(self, field_name, model_class):
        """
        Constructs a URNRelatedField for the given model class.
        """
        field_class = URNIdentityField
        field_kwargs = get_url_kwargs(model_class)
        field_kwargs["urn_resource"] = model_class._meta.model_name
        return field_class, field_kwargs

    def build_field(self, field_name, info, model_class, nested_depth):
        """
        Overrides the default field building to insert URN fields where appropriate.
        """
        if field_name == self.urn_field_name:
            if field_name in info.fields_and_pk:
                raise ImproperlyConfigured("The model already defines a URN field.")
            return self.build_urn_field(field_name, model_class)
        return super().build_field(field_name, info, model_class, nested_depth)

    def build_nested_field(self, field_name, relation_info, nested_depth):  # type: ignore
        """
        Create nested fields for forward and reverse relationships.
        """

        class NestedSerializer(URNModelSerializer):
            class Meta:
                model = relation_info.related_model
                depth = nested_depth - 1
                fields = "__all__"

        field_class = NestedSerializer
        field_kwargs = get_nested_relation_kwargs(relation_info)

        return field_class, field_kwargs


@extend_schema_field(URNSchema)
class URNField(fields.CharField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        validator = URNValidator()
        self.validators.append(validator)
