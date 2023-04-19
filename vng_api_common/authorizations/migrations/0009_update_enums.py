# Generated by Django 2.1.1 on 2019-07-12 15:53

from django.db import migrations
from django.db.models import F, Value
from django.db.models.functions import Lower, Replace


def forward(apps, schema_editor):
    AuthorizationsConfig = apps.get_model("authorizations", "AuthorizationsConfig")
    AuthorizationsConfig.objects.all().update(component=Lower(F("component")))

    Autorisatie = apps.get_model("authorizations", "Autorisatie")
    Autorisatie.objects.all().update(
        component=Lower(F("component")),
        max_vertrouwelijkheidaanduiding=Lower(
            Replace(F("max_vertrouwelijkheidaanduiding"), Value(" "), Value("_"))
        ),
    )


class Migration(migrations.Migration):
    dependencies = [("authorizations", "0008_auto_20190712_1541")]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
