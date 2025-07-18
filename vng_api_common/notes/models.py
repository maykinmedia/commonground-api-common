import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from .constants import NotitieStatus, NotitieType


class NotitieBaseClass(models.Model):
    """
    Abstract model mixin that provides common fields and functionality for notes models.
    This base class is intended to be inherited by other models that require notes.

    Note:
        This is an abstract base class and does not create a database table by itself.
    """

    uuid = models.UUIDField(
        unique=True,
        default=uuid.uuid4,
        help_text=_("Unieke identificatie voor deze notitie"),
    )
    onderwerp = models.CharField(
        max_length=255,
        help_text=_("Korte omschrijving of titel van de notitie"),
    )
    tekst = models.TextField(
        help_text=_("De volledige inhoud of beschrijving van de notitie"),
    )
    aangemaakt_door = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Naam of identificatie van de auteur van de notitie"),
    )
    notitie_type = models.CharField(
        max_length=50,
        default=NotitieType.INTERN,
        choices=NotitieType.choices,
        help_text=_(
            "Intern mag enkel een medewerker zien, extern mag gezien worden door medewerker en de initiator."
        ),
    )
    status = models.CharField(
        max_length=50,
        default=NotitieStatus.CONCEPT,
        choices=NotitieStatus.choices,
    )
    aanmaakdatum = models.DateTimeField(
        auto_now_add=True,
        help_text=_("De datum waarop de handeling is gedaan."),
    )
    wijzigingsdatum = models.DateTimeField(
        auto_now=True,
        help_text=_("Datum en tijd waarop de notitie voor het laatst is gewijzigd"),
    )
    gerelateerd_aan = models.URLField(
        blank=True,
        null=True,
        help_text=_(
            "URL van het gerelateerde object waarop deze notitie van toepassing is"
        ),
    )

    class Meta:
        abstract = True

        verbose_name = _("notitie")
        verbose_name_plural = _("notities")

    def __str__(self):
        return f"{self.onderwerp} ({self.status})"
