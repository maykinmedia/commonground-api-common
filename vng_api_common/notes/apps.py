from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class NotesConfig(AppConfig):
    name = "vng_api_common.notes"
    verbose_name = _("Notes")
