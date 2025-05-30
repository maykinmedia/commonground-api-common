import inspect
from collections import OrderedDict
from functools import reduce
from typing import List, Optional, Tuple, Union

from django.db import models, transaction
from django.db.models import Model
from django.utils.translation import gettext_lazy as _

from dateutil.relativedelta import relativedelta
from rest_framework import fields, serializers
from rest_framework.request import Request
from rest_framework_nested.relations import NestedHyperlinkedRelatedField

from .choices import TextChoicesWithDescriptions
from .descriptors import GegevensGroepType

try:
    # 1.1.x
    from relativedeltafield.utils import format_relativedelta, parse_relativedelta
except ImportError:
    try:
        # 1.0.x
        from relativedeltafield import format_relativedelta, parse_relativedelta
    except ImportError:
        format_relativedelta = None
        parse_relativedelta = None


class DurationField(fields.DurationField):
    def to_internal_value(self, value):
        if isinstance(value, relativedelta):
            return value
        try:
            return parse_relativedelta(str(value))
        except ValueError:
            self.fail("invalid", format="P(n)Y(n)M(n)D")

    def to_representation(self, value) -> Optional[str]:
        if isinstance(value, relativedelta):
            return format_relativedelta(value)
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
    choices: Union[models.Choices, List[Tuple[str, str]]],
) -> str:
    is_dj_choices = inspect.isclass(choices) and issubclass(choices, models.Choices)

    if is_dj_choices:
        _choices = choices.choices
        if issubclass(choices, TextChoicesWithDescriptions):
            descriptions = choices.descriptions()
            _choices = [
                (key, f"({value}) {descriptions[key]}") for key, value in _choices
            ]
    else:
        _choices = choices
    items = [f"* `{key}` - {value}" for key, value in _choices]

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

                default_extra_kwargs = {
                    "required": field_name not in gegevensgroep.optional,
                    "allow_null": False,
                    "allow_blank": field_name in gegevensgroep.optional,
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

    def validate_empty_values(self, data):
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

    def to_representation(self, instance) -> dict:
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

        return ret

    def to_internal_value(self, data):
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


class NestedGegevensGroepMixin:
    """
    Set gegevensgroepdata from validated nested data.

    Usage: include the mixin on the ModelSerializer that has gegevensgroepen.
    """

    def _is_gegevensgroep(self, name: str):
        attr = getattr(self.Meta.model, name)
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


def get_nested_fk_attribute(instance, relation_path):
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


class CacheMixin:
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

    def __init__(self, *args, **kwargs):
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

    def __init__(self, *args, **kwargs):
        self.min_length = kwargs.pop("min_length", 1)
        self.max_length = kwargs.pop("max_length", 1000)
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
