from django.core import checks
from django.core.validators import (
    MinLengthValidator,
)
from django.db import models
from django.utils.translation import gettext_lazy as _

from iso639 import iter_langs

from .constants import BSN_LENGTH, RSIN_LENGTH, VertrouwelijkheidsAanduiding
from .validators import validate_bsn, validate_rsin

LANGUAGE_CHOICES = tuple([(lg.pt2b, lg.name) for lg in iter_langs() if lg.pt2b])


class RSINField(models.CharField):
    default_validators = [validate_rsin, MinLengthValidator(RSIN_LENGTH)]
    description = _("RSIN")

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", RSIN_LENGTH)
        super().__init__(*args, **kwargs)

    def check(self, **kwargs):
        errors = super().check(**kwargs)
        errors.extend(self._check_fixed_max_length_attribute(**kwargs))
        return errors

    def _check_fixed_max_length_attribute(self, **kwargs):
        if self.max_length != RSIN_LENGTH:
            return [
                checks.Error(
                    "RSINField may not override 'max_length' attribute.",
                    obj=self,
                    id="vng_api_common.fields.E001",
                )
            ]
        return []


class BSNField(models.CharField):
    default_validators = [validate_bsn, MinLengthValidator(BSN_LENGTH)]
    description = _("BSN")

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", BSN_LENGTH)
        super().__init__(*args, **kwargs)

    def check(self, **kwargs):
        errors = super().check(**kwargs)
        errors.extend(self._check_fixed_max_length_attribute(**kwargs))
        return errors

    def _check_fixed_max_length_attribute(self, **kwargs):
        if self.max_length != BSN_LENGTH:
            return [
                checks.Error(
                    "BSNField may not override 'max_length' attribute.",
                    obj=self,
                    id="vng_api_common.fields.E002",
                )
            ]
        return []


class LanguageField(models.CharField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", 3)
        kwargs.setdefault("choices", LANGUAGE_CHOICES)
        super().__init__(*args, **kwargs)

    def check(self, **kwargs):
        errors = super().check(**kwargs)
        errors.extend(self._check_fixed_max_length_attribute(**kwargs))
        errors.extend(self._check_choices(**kwargs))
        return errors

    def _check_fixed_max_length_attribute(self, **kwargs):
        if self.max_length != 3:
            return [
                checks.Error(
                    "LanguageField may not override 'max_length' attribute.",
                    obj=self,
                    id="vng_api_common.fields.E003",
                )
            ]
        return []

    def _check_choices(self, **kwargs):
        if self.choices != LANGUAGE_CHOICES:
            return [
                checks.Error(
                    "LanguageField may not override 'choices' attribute.",
                    obj=self,
                    id="vng_api_common.fields.E004",
                )
            ]
        return []


class VertrouwelijkheidsAanduidingField(models.CharField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", 20)
        kwargs.setdefault("choices", VertrouwelijkheidsAanduiding.choices)
        super().__init__(*args, **kwargs)

    def check(self, **kwargs):
        errors = super().check(**kwargs)
        errors.extend(self._check_choices(**kwargs))
        return errors

    def _check_choices(self, **kwargs):
        if self.choices != VertrouwelijkheidsAanduiding.choices:
            return [
                checks.Error(
                    "VertrouwelijkheidsAanduidingField may not override 'choices' attribute.",
                    obj=self,
                    id="vng_api_common.fields.E005",
                )
            ]
        return []
