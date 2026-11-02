import pytest

from vng_api_common.authorizations.models import Applicatie
from vng_api_common.authorizations.serializers import ApplicatieSerializer


@pytest.mark.django_db
def test_alleen_is_gereed_voor_publicatie_defaults_to_false():
    applicatie = Applicatie.objects.create(client_ids=["consumer"], label="Consumer")

    applicatie.refresh_from_db()

    assert applicatie.alleen_is_gereed_voor_publicatie is False


@pytest.mark.django_db
def test_serializer_defaults_to_false():
    serializer = ApplicatieSerializer(
        data={
            "client_ids": ["consumer"],
            "label": "Consumer",
            "heeft_alle_autorisaties": True,
        }
    )

    assert serializer.is_valid(), serializer.errors
    applicatie = serializer.save()
    applicatie.refresh_from_db()

    assert applicatie.alleen_is_gereed_voor_publicatie is False


@pytest.mark.django_db
@pytest.mark.parametrize("alleen_is_gereed_voor_publicatie", [True, False])
def test_serializer_saves_alleen_is_gereed_voor_publicatie(
    alleen_is_gereed_voor_publicatie,
):
    serializer = ApplicatieSerializer(
        data={
            "client_ids": ["consumer"],
            "label": "Consumer",
            "heeft_alle_autorisaties": True,
            "alleen_is_gereed_voor_publicatie": alleen_is_gereed_voor_publicatie,
        }
    )

    assert serializer.is_valid(), serializer.errors
    applicatie = serializer.save()
    applicatie.refresh_from_db()

    assert (
        applicatie.alleen_is_gereed_voor_publicatie is alleen_is_gereed_voor_publicatie
    )


@pytest.mark.django_db
def test_serializer_enables_alleen_is_gereed_voor_publicatie():
    applicatie = Applicatie.objects.create(
        client_ids=["consumer"],
        label="Consumer",
        heeft_alle_autorisaties=True,
        alleen_is_gereed_voor_publicatie=False,
    )
    serializer = ApplicatieSerializer(
        applicatie,
        data={"alleen_is_gereed_voor_publicatie": True},
        partial=True,
    )

    assert serializer.is_valid(), serializer.errors
    serializer.save()
    applicatie.refresh_from_db()

    assert applicatie.alleen_is_gereed_voor_publicatie is True


@pytest.mark.django_db
def test_serializer_disables_alleen_is_gereed_voor_publicatie():
    applicatie = Applicatie.objects.create(
        client_ids=["consumer"],
        label="Consumer",
        heeft_alle_autorisaties=True,
        alleen_is_gereed_voor_publicatie=True,
    )
    serializer = ApplicatieSerializer(
        applicatie,
        data={"alleen_is_gereed_voor_publicatie": False},
        partial=True,
    )

    assert serializer.is_valid(), serializer.errors
    serializer.save()
    applicatie.refresh_from_db()

    assert applicatie.alleen_is_gereed_voor_publicatie is False


@pytest.mark.django_db
def test_partial_update_preserves_alleen_is_gereed_voor_publicatie_when_omitted():
    applicatie = Applicatie.objects.create(
        client_ids=["consumer"],
        label="Consumer",
        heeft_alle_autorisaties=True,
        alleen_is_gereed_voor_publicatie=True,
    )
    serializer = ApplicatieSerializer(
        applicatie, data={"label": "Updated consumer"}, partial=True
    )

    assert serializer.is_valid(), serializer.errors
    serializer.save()
    applicatie.refresh_from_db()

    assert applicatie.alleen_is_gereed_voor_publicatie is True


@pytest.mark.django_db
def test_serializer_rejects_null_for_alleen_is_gereed_voor_publicatie():
    serializer = ApplicatieSerializer(
        data={
            "client_ids": ["consumer"],
            "label": "Consumer",
            "heeft_alle_autorisaties": True,
            "alleen_is_gereed_voor_publicatie": None,
        }
    )

    assert not serializer.is_valid()
    assert serializer.errors["alleen_is_gereed_voor_publicatie"] == [
        "This field may not be null."
    ]


@pytest.mark.django_db
def test_serializer_rejects_text_for_alleen_is_gereed_voor_publicatie():
    serializer = ApplicatieSerializer(
        data={
            "client_ids": ["consumer"],
            "label": "Consumer",
            "heeft_alle_autorisaties": True,
            "alleen_is_gereed_voor_publicatie": "invalid",
        }
    )

    assert not serializer.is_valid()
    assert serializer.errors["alleen_is_gereed_voor_publicatie"] == [
        "Must be a valid boolean."
    ]
