import warnings

from django.db import models
from django.utils.translation import gettext_lazy as _

from .etags import calculate_etag


class ETagMixin(models.Model):
    """
    Mark a model as a resource with ETags.

    The ETags are stored in :class:`StoredETag`; ``_etag`` is no longer maintained
    and remains so models need no migration.
    """

    _etag = models.CharField(
        _("etag value"),
        max_length=32,
        help_text=_("MD5 hash of the resource representation in its current version."),
        editable=False,
    )

    class Meta:
        abstract = True

    def calculate_etag_value(self) -> str:
        """
        Calculate the ETag and save it in ``_etag``.

        .. deprecated:: Use :func:`vng_api_common.caching.calculate_etag`.
        """
        if not self.pk:
            warnings.warn(
                "You should not calculate ETags on unsaved objects", RuntimeWarning
            )
        self._etag = calculate_etag(self)
        self.save(update_fields=["_etag"])
        return self._etag


class StoredETag(models.Model):
    """
    The stored ETag of a resource: see :mod:`vng_api_common.caching.store`.

    A row exists from the first write that affects the resource until its delete.
    """

    model = models.CharField(max_length=255)  # the concrete model's ``label_lower``
    object_id = models.CharField(max_length=255)
    token = models.UUIDField()
    etag = models.CharField(max_length=32, null=True)
    stamp = models.CharField(max_length=32, blank=True)

    class Meta:
        app_label = "vng_api_common"
        constraints = [
            models.UniqueConstraint(
                fields=["model", "object_id"], name="unique_stored_etag"
            )
        ]
