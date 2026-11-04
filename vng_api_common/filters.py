import re
from urllib.parse import urlparse

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models
from django.forms.widgets import URLInput
from django.utils.translation import gettext_lazy as _

import structlog
from django_filters import fields, filters
from django_filters.constants import EMPTY_VALUES
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field

from .constants import FILTER_URL_DID_NOT_RESOLVE
from .utils import NotAViewSet, get_resource_for_path
from .validators import validate_rsin

logger = structlog.stdlib.get_logger(__name__)


class URLModelChoiceField(fields.ModelChoiceField):
    widget = URLInput

    def __init__(self, *args, **kwargs):
        self.instance_path = kwargs.pop("instance_path", None)
        super().__init__(*args, **kwargs)

    # Placeholder - gets replaced by URLModelChoiceFilter
    def _get_request(self):
        return None

    def url_to_pk(self, url: str):
        parsed = urlparse(url)
        path = parsed.path

        # this field only supports local FKs - so if we see a domain that does
        # not match the current host, this cannot possibly yield any results
        request = self._get_request()
        if request is not None:
            host = request.get_host()
            if parsed.netloc != host:
                raise NotAViewSet("External URL cannot map to a local viewset")

        instance = get_resource_for_path(path)
        if self.instance_path:
            for bit in self.instance_path.split("."):
                instance = getattr(instance, bit)
        if self.queryset is None:
            raise ValueError("queryset must be set before calling url_to_pk")
        model = self.queryset.model
        if not isinstance(instance, model):
            raise ValidationError(
                _("Invalid resource type supplied, expected %r") % model,
                code="invalid-type",
            )
        return instance.pk

    def to_python(self, value: str):
        if value is not None:
            URLValidator()(value)

        if value:
            try:
                value = self.url_to_pk(value)
            except NotAViewSet:
                logger.info(
                    "resource_not_found",
                    resource=self.label,
                    url=value,
                )
                return FILTER_URL_DID_NOT_RESOLVE
            except models.ObjectDoesNotExist:
                logger.info(
                    "resource_not_found",
                    resource=self.label,
                    url=value,
                )
                return FILTER_URL_DID_NOT_RESOLVE
        return super().to_python(value)


@extend_schema_field(OpenApiTypes.URI)
class URLModelChoiceFilter(filters.ModelChoiceFilter):
    field_class = URLModelChoiceField

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance_path = kwargs.get("instance_path")
        self.queryset = kwargs.get("queryset")

    @property
    def field(self):
        field = super().field
        # we need access to the request in the backing field...
        field._get_request = self.get_request  # type: ignore[attr-defined]
        return field

    def filter(self, qs, value):
        # If the URL did not resolve to an instance, return no results
        if value == FILTER_URL_DID_NOT_RESOLVE:
            return qs.none()
        return super().filter(qs, value)


class RSINFilter(filters.CharFilter):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("validators", [validate_rsin])
        super().__init__(*args, **kwargs)


class WildcardFilter(filters.CharFilter):
    """
    Filters the queryset based on a string and optionally allows wildcards in
    the query parameter.
    """

    wildcard = "*"

    def __init__(self, *args, **kwargs):
        kwargs["lookup_expr"] = "iregex"
        super().__init__(*args, **kwargs)

    def filter(self, qs, value):
        if value in EMPTY_VALUES:
            return qs

        value = r"^{}$".format(value.replace(self.wildcard, ".*"))

        return super().filter(qs, value)


class URNFilter(filters.CharFilter):
    """
    Filters by an exact segment of a URN field.

    Unlike a generic substring match (icontains), the value must match
    a whole segment delimited by ``:``.
    """

    @staticmethod
    def get_pattern(value):
        return r"(^|:)" + re.escape(value) + r"(:|$)"

    def filter(self, qs, value):
        if value in EMPTY_VALUES:
            return qs

        pattern = self.get_pattern(value)
        return self.get_method(qs)(**{f"{self.field_name}__regex": pattern})


class ListURNFilter(filters.CharFilter):
    """
    Filters by an exact URN segment within a JSONField containing a
    list of URNs. Supports two shapes:

    - a list of plain URN strings
    - a list of URN objects
    """

    def __init__(self, *args, json_key="urn", **kwargs):
        self.json_key = json_key
        super().__init__(*args, **kwargs)

    def filter(self, qs, value):
        if value in EMPTY_VALUES:
            return qs

        json_key = self.json_key
        pattern = URNFilter.get_pattern(value)

        class MatchesURN(models.Func):
            output_field = models.BooleanField()  # pyright: ignore[reportAssignmentType]

            def as_sql(self, compiler, connection, **extra_context):  # type: ignore
                column, params = compiler.compile(self.source_expressions[0])
                return (
                    "EXISTS (SELECT 1 FROM jsonb_array_elements("
                    f"COALESCE(NULLIF({column}, 'null'::jsonb), '[]'::jsonb)) e "
                    "WHERE (CASE WHEN jsonb_typeof(e) = 'object' THEN e->>%s "
                    "WHEN jsonb_typeof(e) = 'string' THEN e#>>'{}' END) ~ %s)",
                    [*params, json_key, pattern],
                )

        condition = MatchesURN(models.F(self.field_name))  # pyright: ignore[reportArgumentType]
        return self.get_method(qs)(condition)
