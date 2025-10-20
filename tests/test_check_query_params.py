import django_filters
import pytest
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from rest_framework.test import APIRequestFactory

from testapp.models import Group
from testapp.viewsets import GroupViewSet as _GroupViewSet
from vng_api_common.viewsets import CheckQueryParamsMixin


class GroupFilter(django_filters.FilterSet):
    expand = django_filters.CharFilter(method="filter_expand")

    class Meta:
        model = Group
        fields = []

    def filter_expand(self, queryset, name, value):
        return queryset


class CustomOrderingFilter(OrderingFilter):
    ordering_param = "custom_ordering"


class GroupViewSet(CheckQueryParamsMixin, _GroupViewSet):
    filter_backends = (OrderingFilter,)


@pytest.mark.django_db
def test_check_query_params_list_view_allowed():
    Group.objects.create(name="Test Group")
    factory = APIRequestFactory()

    # default filtering
    request = factory.get("/groups", data={"ordering": "datum"}, format="json")
    view = GroupViewSet.as_view({"get": "list"})
    response = view(request)

    assert response.status_code == 200
    assert response.data == [{"persons": [], "nested_persons": []}]

    # custom filtering
    GroupViewSet.filter_backends = (CustomOrderingFilter,)

    request = factory.get("/groups", data={"custom_ordering": "datum"}, format="json")
    view = GroupViewSet.as_view({"get": "list"})
    response = view(request)

    assert response.status_code == 200
    assert response.data == [{"persons": [], "nested_persons": []}]


@pytest.mark.django_db
def test_check_query_params_list_view_not_allowed():
    GroupViewSet.filter_backends = (CustomOrderingFilter,)
    Group.objects.create(name="Test Group")
    factory = APIRequestFactory()

    # Incorrect parameters should still be blocked
    request = factory.get("/groups", data={"invalid_ordering": "datum"}, format="json")
    view = GroupViewSet.as_view({"get": "list"})
    response = view(request)

    assert response.status_code == 400
    assert response.data["invalid_params"] == [
        {
            "name": "nonFieldErrors",
            "code": "unknown-parameters",
            "reason": "Onbekende query parameters: invalid_ordering",
        }
    ]


@pytest.mark.django_db
def test_check_query_params_detail_view_allowed():
    GroupViewSet.filter_backends = (DjangoFilterBackend,)
    GroupViewSet.filterset_class = GroupFilter
    group = Group.objects.create(name="Test Group")
    factory = APIRequestFactory()

    detail_request = factory.get(
        f"/groups/{group.id}/", data={"expand": "persons"}, format="json"
    )
    view = GroupViewSet.as_view({"get": "retrieve"})
    response = view(detail_request, pk=group.id)

    assert response.status_code == 200
    assert response.data == {"persons": [], "nested_persons": []}


@pytest.mark.django_db
def test_check_query_params_detail_view_not_allowed():
    GroupViewSet.filter_backends = (DjangoFilterBackend,)
    GroupViewSet.filterset_class = GroupFilter
    group = Group.objects.create(name="Test Group")
    factory = APIRequestFactory()

    detail_request = factory.get(
        f"/groups/{group.id}/", data={"invali_expand": "persons"}, format="json"
    )
    view = GroupViewSet.as_view({"get": "retrieve"})
    response = view(detail_request, pk=group.id)

    assert response.status_code == 400
    assert response.data["invalid_params"] == [
        {
            "name": "nonFieldErrors",
            "code": "unknown-parameters",
            "reason": "Onbekende query parameters: invali_expand",
        }
    ]
