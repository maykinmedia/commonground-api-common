from django_setup_configuration.models import ConfigurationModel
from pydantic import Field

from vng_api_common.authorizations.models import Applicatie
from vng_api_common.models import JWTSecret


class SingleJWTSecretConfigurationModel(ConfigurationModel):
    class Meta:
        django_model_refs = {
            JWTSecret: [
                "identifier",
                "secret",
            ]
        }
        extra_kwargs = {
            "identifier": {"examples": ["application-name"]},
            "secret": {"examples": ["modify-this"]},
        }


class JWTSecretsConfigurationModel(ConfigurationModel):
    items: list[SingleJWTSecretConfigurationModel] = Field()


class SingleApplicatieConfigurationModel(ConfigurationModel):
    client_ids: list[str]

    class Meta:
        django_model_refs = {
            Applicatie: ["uuid", "client_ids", "label", "heeft_alle_autorisaties"]
        }
        extra_kwargs = {
            "uuid": {
                # FIXME workaround for https://github.com/maykinmedia/django-setup-configuration/issues/58
                "default": "17fd9f07-6b2f-4168-9262-d4d17c3e669b"
            },
            "client_ids": {"examples": [["open-notificaties-prod"]]},
            "label": {"examples": ["Open Notificaties (productie)"]},
        }


class ApplicatieConfigurationModel(ConfigurationModel):
    items: list[SingleApplicatieConfigurationModel] = Field()
