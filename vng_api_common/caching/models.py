import warnings

from django.db import models
from django.utils.translation import gettext_lazy as _

from .etags import calculate_etag


class ETagMixin(models.Model):
    """
    Keep the ``_etag`` column of an existing model, so it needs no migration.

    The ETags are stored in :class:`StoredETag`; ``_etag`` is no longer maintained.

    .. deprecated:: New models don't need it. Drop it from existing ones in two
      releases, as the HTTP caching docs show: the ``RemoveField`` that
      ``makemigrations`` writes drops the column in one step, which breaks a rolling
      deploy (check ``vng_api_common.caching.W001``).
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
        Calculate the ETag and save it in ``_etag``. The save invalidates the
        stored ETag, so this still does after a ``QuerySet.update`` what it did.

        .. deprecated:: Use :func:`~vng_api_common.caching.invalidating_update`
          instead of ``QuerySet.update``.
        """
        warnings.warn(
            "calculate_etag_value is deprecated: use invalidating_update instead of "
            "QuerySet.update. To drop ETagMixin, don't use the RemoveField "
            "makemigrations writes: see the HTTP caching docs",
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
