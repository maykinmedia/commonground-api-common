import warnings

from django.db import models
from django.utils.translation import gettext_lazy as _

from .etags import calculate_etag


class ETagMixin(models.Model):
    """
    Keep the ``_etag`` column of an existing model, so it needs no migration.

    The ETags are stored in :class:`StoredETag`; ``_etag`` is no longer maintained.

    .. deprecated:: New models don't need it; drop it from existing ones.
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
        Calculate and save the ETag value.

        .. deprecated:: Use :func:`~vng_api_common.caching.invalidating_update`
          instead of ``QuerySet.update``.
        """
        warnings.warn(
            "calculate_etag_value is deprecated: use invalidating_update instead of "
            "QuerySet.update",
            DeprecationWarning,
            stacklevel=2,
        )
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
