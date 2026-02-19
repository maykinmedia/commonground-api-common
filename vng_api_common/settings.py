from django.conf import settings

__all__ = ["get_setting"]

DEFAULTS = {
    "API_EXCEPTION_CAMELIZE": True,
}


def get_setting(name: str):
    return getattr(settings, name, DEFAULTS.get(name))


API_EXCEPTION_CAMELIZE = get_setting("API_EXCEPTION_CAMELIZE")
