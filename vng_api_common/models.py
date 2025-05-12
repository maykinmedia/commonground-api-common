from django.db import models
from django.utils.translation import gettext_lazy as _

from rest_framework.reverse import reverse


class APIMixin:
    """
    Determine the absolute URL of a resource in the API.

    Model mixin that reverses the URL-path in the API based on the
    ``uuid``-field of a model instance.
    """

    _cached_url_path = None

    # Store as classvar to make sure it is cached per model
    def _set_reverse_path(self, value: str) -> None:
        type(self)._cached_url_path = value

    def _get_reverse_path(self) -> str | None:
        if hasattr(type(self), "_cached_url_path"):
            return type(self)._cached_url_path

    def get_absolute_api_url(self, request=None, **kwargs) -> str:
        # FIXME this currently doesn't work with different API versions
        resource_name = self._meta.model_name

        reverse_kwargs = {"uuid": "id-placeholder"}
        reverse_kwargs.update(**kwargs)
        if not (url := self._get_reverse_path()):
            url = reverse(f"{resource_name}-detail", kwargs=reverse_kwargs)
            self._set_reverse_path(url)

        url = url.replace("id-placeholder", str(self.uuid))
        if request:
            url = request.build_absolute_uri(url)
        return url


class JWTSecretManager(models.Manager):
    def get_by_natural_key(self, identifier):
        return self.get(identifier=identifier)


class JWTSecret(models.Model):
    """
    Store credentials of clients that want to access our API.

    Only clients that are known can access the API (if so configured).
    """

    identifier = models.CharField(
        _("client ID"),
        max_length=50,
        unique=True,
        help_text=_(
            "Client ID to identify external API's and applications that access this API."
        ),
    )
    secret = models.CharField(
        _("secret"), max_length=255, help_text=_("Secret belonging to the client ID.")
    )

    objects = JWTSecretManager()

    def natural_key(self):
        return (self.identifier,)

    class Meta:
        verbose_name = _("client credential")
        verbose_name_plural = _("client credentials")

    def __str__(self):
        return self.identifier
