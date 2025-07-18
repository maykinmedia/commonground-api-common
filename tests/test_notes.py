import datetime

import pytest
from freezegun import freeze_time
from rest_framework import status
from rest_framework.reverse import reverse

from testapp.factories import NotitieFactory
from testapp.models import Notitie
from vng_api_common.notes.constants import NotitieStatus, NotitieType


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


@freeze_time("2025-07-08")
@pytest.mark.django_db
def test_api_filters(api_client):
    NotitieFactory.create(
        onderwerp="test_onderwerp",
        tekst="notitie test1",
        aangemaakt_door="test_user_a",
        status=NotitieStatus.CONCEPT.value,
        notitie_type=NotitieType.INTERN.value,
        gerelateerd_aan="https://testserver.com/object/",
    )
    NotitieFactory.create(
        aangemaakt_door="test_user_b",
        status=NotitieStatus.CONCEPT.value,
        notitie_type=NotitieType.EXTERN.value,
    )
    NotitieFactory.create(
        status=NotitieStatus.DEFINITIEF.value,
        notitie_type=NotitieType.INTERN.value,
    )
    list_url = reverse("notitie-list")

    # filter_status:
    response = api_client.get(list_url, {"status": NotitieStatus.CONCEPT.value})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 2
    assert response.json()[0]["status"] == NotitieStatus.CONCEPT.value

    # filter_notitie_type:
    response = api_client.get(list_url, {"notitieType": NotitieType.EXTERN.value})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 1
    assert response.json()[0]["notitieType"] == NotitieType.EXTERN.value

    # filter_onderwerp:
    response = api_client.get(list_url, {"onderwerp": "wrong"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 0

    response = api_client.get(list_url, {"onderwerp": "test_onderwerp"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 1

    response = api_client.get(list_url, {"onderwerp__icontains": "test_"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 1

    # filter_aangemaakt_door:
    response = api_client.get(list_url, {"aangemaakt_door": "wrong"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 0

    response = api_client.get(list_url, {"aangemaakt_door": "test_user_a"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 1

    response = api_client.get(list_url, {"aangemaakt_door__icontains": "test_user"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 2

    # filter_tekst:
    response = api_client.get(list_url, {"tekst": "wrong"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 0

    response = api_client.get(list_url, {"tekst": "notitie test1"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 1

    response = api_client.get(list_url, {"tekst__icontains": "test1"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 1

    dt = datetime.datetime(2025, 7, 8, 15, 20, 0)

    # filter_wijzigingsdatum:
    response = api_client.get(list_url, {"wijzigingsdatum": "2025-07-08"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 3

    response = api_client.get(list_url, {"wijzigingsdatum__gt": "2025-07-08"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 0

    dt += datetime.timedelta(days=10)
    with freeze_time((dt + datetime.timedelta(days=10)).isoformat()):
        for notitie in Notitie.objects.filter(status=NotitieStatus.CONCEPT.value):
            notitie.wijzigingsdatum = dt
            notitie.save()

    response = api_client.get(list_url, {"wijzigingsdatum__gt": "2025-07-08"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 2

    # filter_gerelateerd_aan:
    response = api_client.get(
        list_url, {"gerelateerd_aan": "https://testserver.com/wrong/"}
    )
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 0

    response = api_client.get(
        list_url, {"gerelateerd_aan": "https://testserver.com/object/"}
    )
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 1

    # filter_aanmaakdatum:
    response = api_client.get(list_url, {"aanmaakdatum__date": "2025-07-08"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 3

    response = api_client.get(list_url, {"aanmaakdatum__gt": "2025-07-08"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 0

    response = api_client.get(list_url, {"aanmaakdatum__lt": "2025-07-08"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 0

    response = api_client.get(list_url, {"aanmaakdatum__date__lte": "2025-07-08"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 3
