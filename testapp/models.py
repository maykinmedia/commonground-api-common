from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.gis.db.models import GeometryField
from django.db import models
from django.utils.translation import gettext_lazy as _

from vng_api_common.caching import ETagMixin
from vng_api_common.descriptors import GegevensGroepType
from vng_api_common.fields import BSNField, RSINField
from vng_api_common.notes.models import NotitieBaseClass

if TYPE_CHECKING:
    from django.db.models.fields.related_descriptors import (
        ManyRelatedManager,
        RelatedManager,
    )


class Group(models.Model):
    name = models.CharField(_("name"), max_length=100)

    subgroup_field_1 = models.CharField(max_length=50, blank=True)
    subgroup_field_2 = models.CharField(max_length=50, blank=True, default="baz")

    subgroup = GegevensGroepType(
        {"field_1": subgroup_field_1, "field_2": subgroup_field_2},
        optional=("field_2",),
    )


class Person(ETagMixin, models.Model):
    name = models.CharField(_("name"), max_length=50)

    address_street = models.CharField(_("street name"), max_length=255)
    address_number = models.CharField(_("house number"), max_length=10)

    address = GegevensGroepType(
        {"street": address_street, "number": address_number}, required=False
    )

    group = models.ForeignKey("Group", null=True, on_delete=models.CASCADE)

    hobbies = models.ManyToManyField("Hobby", related_name="people", blank=True)


class Hobby(ETagMixin, models.Model):
    name = models.CharField(_("name"), max_length=100)


class Record(models.Model):
    identificatie = models.CharField(_("identificatie"), max_length=50, unique=True)
    create_date = models.DateField(_("create date"))


class PolyChoice(models.TextChoices):
    hobby = "hobby", _("Hobby.")
    record = "record", _("Record")


class Poly(models.Model):
    name = models.CharField(_("name"), max_length=100)
    choice = models.CharField(_("choice"), choices=PolyChoice.choices, max_length=6)


class FkModel(models.Model):
    name = models.CharField(
        _("name"), max_length=100, help_text="FkModel simple name help_text"
    )
    field_with_underscores = models.CharField(_("name"), max_length=100)
    poly = models.ForeignKey(
        verbose_name=_("poly"),
        on_delete=models.deletion.CASCADE,
        to=Poly,
    )
    attribute1 = models.CharField(
        _("attribute1"), max_length=100, blank=True, help_text="charfield"
    )
    attribute2 = models.CharField(
        _("attribute2"),
        choices=[("op1", "Option 1"), ("op2", "Option 2")],
        blank=True,
        help_text="choicefield",
    )

    gegevensgroep = GegevensGroepType(
        {"attribute1": attribute1, "attribute2": attribute2},
    )
    gegevensgroep_optional = GegevensGroepType(
        {"attribute1": attribute1, "attribute2": attribute2},
        optional=(
            "attribute1",
            "attribute2",
        ),
    )
    gegevensgroep_allow_blank = GegevensGroepType({"attribute1": attribute1})


class MediaFileModel(models.Model):
    name = models.CharField(_("name"), max_length=100)
    file = models.FileField(
        _("file"),
        upload_to="uploads/",
    )


class GeometryModel(models.Model):
    name = models.CharField(_("name"), max_length=100)
    zaakgeometrie = GeometryField(
        blank=True,
        null=True,
        help_text="Punt, lijn of (multi-)vlak geometrie-informatie.",
    )


class Notitie(NotitieBaseClass):
    class Meta(NotitieBaseClass.Meta):
        verbose_name = "notitie"
        verbose_name_plural = "notities"


class Medewerker(models.Model):
    bsn = BSNField(blank=True, null=True)
    rsin = RSINField(blank=True, null=True)


# The ETag oracle (tests/test_etag_oracle.py) writes to these models. Between
# them, the representations make every kind of read an ETag has to follow.


class Folder(ETagMixin, models.Model):
    name = models.CharField(max_length=10)
    code = models.CharField(max_length=10)  # shown by its sheets, through a slug

    if TYPE_CHECKING:  # reverse relations, which Django adds at runtime
        sheets: RelatedManager[Sheet]
        tags: ManyRelatedManager[Tag, models.Model]
        attachments: RelatedManager[Attachment]
        shortcuts: RelatedManager[Shortcut]

    class Meta:  # type: ignore
        ordering = ["pk"]


class Sheet(ETagMixin, models.Model):
    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, related_name="sheets")
    title = models.CharField(max_length=10)
    position = models.IntegerField()  # orders its folder's list of sheets

    class Meta:  # type: ignore
        ordering = ["position", "pk"]


class Tag(ETagMixin, models.Model):
    label = models.CharField(max_length=10)
    folders = models.ManyToManyField(Folder, related_name="tags", blank=True)

    class Meta:  # type: ignore
        ordering = ["pk"]


class Attachment(models.Model):
    """No ETag of its own: its folder shows it nested."""

    folder = models.ForeignKey(
        Folder, on_delete=models.CASCADE, related_name="attachments"
    )
    filename = models.CharField(max_length=10)

    class Meta:  # type: ignore
        ordering = ["pk"]


class Shortcut(ETagMixin, models.Model):
    label = models.CharField(max_length=10)
    target = models.ForeignKey(
        Folder, on_delete=models.SET_NULL, null=True, related_name="shortcuts"
    )

    class Meta:  # type: ignore
        ordering = ["pk"]
