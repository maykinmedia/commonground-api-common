from django.db.models import TextChoices
from django.utils.functional import Promise


def ensure_description_exists(text_choices):
    descriptions = text_choices.descriptions()

    for choice, text in text_choices.choices:
        if choice not in descriptions:
            raise ValueError(
                f"Choice ({choice}, {text}) in {text_choices.__name__} is missing a description"
            )
    return text_choices


class TextChoicesWithDescriptions(TextChoices):
    @classmethod
    def descriptions(cls) -> dict[str, str | Promise]:
        return {}
