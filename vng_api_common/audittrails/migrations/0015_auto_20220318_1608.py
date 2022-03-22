# Generated by Django 2.2.27 on 2022-03-18 16:08

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audittrails", "0014_auto_20201221_0905"),
    ]

    operations = [
        migrations.AlterField(
            model_name="audittrail",
            name="bron",
            field=models.CharField(
                choices=[
                    ("ac", "Autorisaties API"),
                    ("nrc", "Notificaties API"),
                    ("zrc", "Zaken API"),
                    ("ztc", "Catalogi API"),
                    ("drc", "Documenten API"),
                    ("brc", "Besluiten API"),
                    ("cmc", "Contactmomenten API"),
                    ("kc", "Klanten API"),
                    ("vrc", "Verzoeken API"),
                ],
                help_text="De naam van het component waar de wijziging in is gedaan.",
                max_length=50,
            ),
        ),
    ]
