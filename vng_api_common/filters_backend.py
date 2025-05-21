import logging
from urllib.parse import urlencode

from django.db import models
from django.http import QueryDict

from django_filters.rest_framework import DjangoFilterBackend
from djangorestframework_camel_case.parser import CamelCaseJSONParser
from djangorestframework_camel_case.render import CamelCaseJSONRenderer
from djangorestframework_camel_case.util import underscoreize
from rest_framework.request import Request
from rest_framework.views import APIView

from .filtersets import FilterSet
from .search import is_search_view

logger = logging.getLogger(__name__)


class Backend(DjangoFilterBackend):
    filterset_base = FilterSet

    def _is_camel_case(self, view):
        return any(
            issubclass(parser, CamelCaseJSONParser) for parser in view.parser_classes
        ) or any(
            issubclass(renderer, CamelCaseJSONRenderer)
            for renderer in view.renderer_classes
        )

    def _transform_query_params(self, view, query_params: QueryDict) -> QueryDict:
        if not self._is_camel_case(view):
            return query_params

        # data can be a regular dict if it's coming from a serializer
        if hasattr(query_params, "lists"):
            data = dict(query_params.lists())
        else:
            data = query_params

        transformed = underscoreize(data)

        return QueryDict(urlencode(transformed, doseq=True))

    def get_filterset_kwargs(
        self, request: Request, queryset: models.QuerySet, view: APIView
    ):
        """
        Get the initialization parameters for the filterset.

        * filter on request.data if request.query_params is empty
        * do the camelCase transformation of filter parameters
        """
        kwargs = super().get_filterset_kwargs(request, queryset, view)
        filter_parameters = (
            request.query_params if not is_search_view(view) else request.data
        )
        query_params = self._transform_query_params(view, filter_parameters)
        kwargs["data"] = query_params
        return kwargs
