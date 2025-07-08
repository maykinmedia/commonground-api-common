import datetime

import pytest
from freezegun import freeze_time
from rest_framework import status
from rest_framework.reverse import reverse

from testapp.factories import NotitieFactory
from testapp.models import Notitie


@pytest.mark.django_db
def test_notitie_model():
    assert Notitie.objects.count() == 0
    NotitieFactory.create()
    assert Notitie.objects.count() == 1


@pytest.mark.django_db
@freeze_time("2025-07-08T14:20:00")
def test_api_list(api_client):
    assert Notitie.objects.count() == 0

    response = api_client.get(reverse("notitie-list"))
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == []

    notitie = NotitieFactory.create()
    assert Notitie.objects.count() == 1
    response = api_client.get(reverse("notitie-list"))
    data = response.json()
    assert len(data) == 1
    assert data == [
        {
            "onderwerp": notitie.onderwerp,
            "tekst": notitie.tekst,
            "aangemaaktDoor": notitie.aangemaakt_door,
            "notitieType": notitie.notitie_type,
            "status": notitie.status,
            "aanmaakdatum": notitie.aanmaakdatum.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "wijzigingsdatum": notitie.wijzigingsdatum.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "gerelateerdAan": notitie.gerelateerd_aan,
        }
    ]


@pytest.mark.django_db
@freeze_time("2025-07-08T14:20:00")
def test_api_create(api_client):
    data = {
        "onderwerp": "Test Onderwerp",
        "tekst": "Test Tekst",
        "aangemaaktDoor": "test_user",
        "notitieType": "extern",
        "status": "definitief",
        "gerelateerdAan": "http://localhost:8000/test",
    }

    response = api_client.post(reverse("notitie-list"), data, format="json")
    assert response.status_code == status.HTTP_201_CREATED

    notitie = Notitie.objects.get()
    assert notitie.onderwerp == response.data["onderwerp"]
    assert notitie.tekst == response.data["tekst"]
    assert notitie.aangemaakt_door == response.data["aangemaakt_door"]
    assert notitie.notitie_type == response.data["notitie_type"]
    assert notitie.status == response.data["status"]
    assert notitie.gerelateerd_aan == response.data["gerelateerd_aan"]
    assert str(notitie.aanmaakdatum) == "2025-07-08 14:20:00+00:00"
    assert str(notitie.wijzigingsdatum) == "2025-07-08 14:20:00+00:00"


@pytest.mark.django_db
@freeze_time("2025-07-08T14:20:00")
def test_api_retrieve(api_client):
    notitie = NotitieFactory.create()
    url = reverse("notitie-detail", args=[notitie.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "onderwerp": notitie.onderwerp,
        "tekst": notitie.tekst,
        "aangemaaktDoor": notitie.aangemaakt_door,
        "notitieType": notitie.notitie_type,
        "status": notitie.status,
        "aanmaakdatum": notitie.aanmaakdatum.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "wijzigingsdatum": notitie.wijzigingsdatum.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gerelateerdAan": notitie.gerelateerd_aan,
    }


@pytest.mark.django_db
def test_api_update(api_client):
    dt = datetime.datetime(2025, 7, 8, 15, 20, 0)
    with freeze_time(dt.isoformat()):
        notitie = NotitieFactory.create(onderwerp="Old Value")
        assert notitie.onderwerp == "Old Value"
        assert str(notitie.aanmaakdatum) == "2025-07-08 15:20:00+00:00"
        assert str(notitie.aanmaakdatum) == str(notitie.wijzigingsdatum)

    with freeze_time((dt + datetime.timedelta(seconds=60)).isoformat()):
        url = reverse("notitie-detail", args=[notitie.id])
        response = api_client.patch(url, {"onderwerp": "New Value"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        notitie = Notitie.objects.get()
        assert notitie.onderwerp != "Old Value"
        assert notitie.onderwerp == "New Value"

        assert str(notitie.aanmaakdatum) == "2025-07-08 15:20:00+00:00"
        assert str(notitie.wijzigingsdatum) == "2025-07-08 15:21:00+00:00"
        assert str(notitie.aanmaakdatum) != str(notitie.wijzigingsdatum)


@pytest.mark.django_db
def test_api_delete(api_client):
    notitie = NotitieFactory.create()
    assert Notitie.objects.count() == 1
    url = reverse("notitie-detail", args=[notitie.id])
    response = api_client.delete(url)
    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert Notitie.objects.count() == 0
