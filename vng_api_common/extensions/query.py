from drf_spectacular.contrib.django_filters import DjangoFilterExtension

from vng_api_common.utils import underscore_to_camel


class CamelizeFilterExtension(DjangoFilterExtension):
    priority = 1

    def get_schema_operation_parameters(self, auto_schema, *args, **kwargs):
        """
        camelize query parameters
        """
        parameters = super().get_schema_operation_parameters(
            auto_schema, *args, **kwargs
        )

        for parameter in parameters:
            parameter["name"] = underscore_to_camel(parameter["name"])

        return parameters

    def resolve_filter_field(
        self, auto_schema, model, filterset_class, field_name, filter_field
    ):
        """
        Keep the help_text/label description for filters whose schema is set
        via ``@extend_schema_field`` (drf-spectacular drops it otherwise).
        """
        parameters = super().resolve_filter_field(
            auto_schema, model, filterset_class, field_name, filter_field
        )

        for parameter in parameters:
            if not parameter.get("description"):
                description = self._get_field_description(filter_field, None)
                if description:
                    parameter["description"] = description

        return parameters
