from typing import TYPE_CHECKING

from django.db import models

from rest_framework.response import Response

if TYPE_CHECKING:
    from rest_framework.viewsets import GenericViewSet as _BaseView  # or ViewSet
else:
    _BaseView = object


def is_search_view(view):
    _action = getattr(view, "action", None)
    if _action is None:
        return
    action = getattr(view, view.action)
    return getattr(action, "is_search_action", False)


class SearchMixin(_BaseView):
    search_input_serializer_class = None

    def get_search_input_serializer_class(self):
        return self.search_input_serializer_class or self.serializer_class

    def get_search_input(self):
        SerializerClass = self.get_search_input_serializer_class()
        assert SerializerClass is not None, "No serializer class set"
        serializer = SerializerClass(data=self.request.data)  # type: ignore
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def get_search_output(self, queryset: models.QuerySet):
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
