from django.conf import settings

_SETTINGS_NAMESPACE = "COMMONGROUND_API_COMMON"


#: Defaults for library settings
#:
#: Can be overridden by configuring the ``COMMONGROUND_API_COMMON`` setting
#:
#: .. code-block:: python
#:
#:     COMMONGROUND_API_COMMON = {
#:         "API_EXCEPTION_CAMELIZE": True,
#:     }
#:
COMMONGROUND_API_COMMON = {
    "API_EXCEPTION_CAMELIZE": True,
}


def get_setting(name: str):
    """Return the value for a setting."""
    user_settings = getattr(settings, _SETTINGS_NAMESPACE, {})
    return user_settings.get(name, COMMONGROUND_API_COMMON.get(name))
