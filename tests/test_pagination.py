import pytest
from rest_framework import status
from rest_framework.reverse import reverse

from testapp.factories import HobbyFactory
from vng_api_common.pagination import DynamicPageSizeMixin


@pytest.mark.django_db
def test_list_with_default_page_size(api_client):
    HobbyFactory.create_batch(10)
    path = reverse("paginate-hobby-list")

    response = api_client.get(path)

    assert response.status_code == status.HTTP_200_OK

    data = response.json()

    assert data["count"] == 10
    assert data["next"] is None


@pytest.mark.django_db
def test_list_with_page_size_in_query(api_client):
    HobbyFactory.create_batch(10)
    path = reverse("paginate-hobby-list")

    response = api_client.get(path, {"pageSize": 5})
    assert response.status_code == status.HTTP_200_OK

    data = response.json()

    assert data["count"] == 10
    assert len(data["results"]) == 5
    assert data["next"] == f"http://testserver{path}?page=2&pageSize=5"


def test_page_size_query_description_property():
    class DummyPagination(DynamicPageSizeMixin):
        page_size = 42

    pagination = DummyPagination()
    assert (
        pagination.page_size_query_description
        == "Het aantal resultaten terug te geven per pagina. (default: 42)."
    )
