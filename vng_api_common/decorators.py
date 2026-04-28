from typing import TypeVar, cast

from django.db import models

T = TypeVar("T", bound=type[models.Model])


def field_default(field: str, default: object):
    def decorator(cls: T) -> T:
        model_field = cast(models.Field, cls._meta.get_field(field))
        model_field.default = default
        return cls

    return decorator
