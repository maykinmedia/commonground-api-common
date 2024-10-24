# Generated by Django 5.1.2 on 2024-10-24 13:51

import logging

from django.db import migrations

from zgw_consumers.constants import APITypes, AuthTypes

logger = logging.getLogger(__name__)


def migrate_credentials_to_service(apps, _) -> None:
    APICredential = apps.get_model("vng_api_common", "APICredential")
    Service = apps.get_model("zgw_consumers", "Service")

    credentials = APICredential.objects.all()

    for credential in credentials:
        logger.info("Creating Service for {credential.client_id")

        _, created = Service.objects.get_or_create(
            api_root=credential.api_root,
            defaults=dict(
                label=credential.label,
                api_type=APITypes.orc,
                auth_type=AuthTypes.zgw,
                client_id=credential.client_id,
                secret=credential.secret,
                user_id=credential.user_id,
                user_representation=credential.user_representation,
            ),
        )

        if created:
            logger.info("Created new Service for {credential.api_root}")
        else:
            logger.info("Existing service found for {credential.api_root}")


class Migration(migrations.Migration):

    dependencies = [
        ("vng_api_common", "0005_auto_20190614_1346"),
    ]

    operations = [
        migrations.RunPython(migrate_credentials_to_service),
        migrations.DeleteModel(
            name="APICredential",
        ),
    ]
