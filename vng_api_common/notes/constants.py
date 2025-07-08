from django.db import models
from django.utils.translation import gettext_lazy as _


class NotitieType(models.TextChoices):
    INTERN = "intern", _("Intern")
    EXTERN = "extern", _("Extern")


class NotitieStatus(models.TextChoices):
    CONCEPT = "concept", _("Concept")
    DEFINITIEF = "definitief", _("Definitief")
