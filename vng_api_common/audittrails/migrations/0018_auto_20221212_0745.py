# Generated by Django 3.2.16 on 2022-12-12 07:45

import django.core.serializers.json
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audittrails", "0017_alter_audittrail_bron"),
    ]

    operations = [
        migrations.AlterField(
            model_name="audittrail",
            name="nieuw",
            field=models.JSONField(
                encoder=django.core.serializers.json.DjangoJSONEncoder,
                help_text="Volledige JSON body van het object na de actie.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="audittrail",
            name="oud",
            field=models.JSONField(
                encoder=django.core.serializers.json.DjangoJSONEncoder,
                help_text="Volledige JSON body van het object zoals dat bestond voordat de actie heeft plaatsgevonden.",
                null=True,
            ),
        ),
    ]