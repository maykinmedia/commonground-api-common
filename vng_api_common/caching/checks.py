from collections.abc import Iterable, Sequence

from django.apps import AppConfig
from django.core.checks import CheckMessage, Tags, Warning, register
from django.db.migrations import RemoveField
from django.db.migrations.loader import MigrationLoader


@register(Tags.database)
def check_etag_column_drops(
    app_configs: Sequence[AppConfig] | None, **kwargs: object
) -> Iterable[CheckMessage]:
    """
    Warn about a migration that drops ``_etag`` with a plain ``RemoveField``, as
    ``makemigrations`` writes one when a model drops ``ETagMixin``: processes of the
    release before still select the column during a rolling deploy.

    A database check, so ``migrate`` runs it, and loading the migrations doesn't
    slow down every ``runserver``.
    """
    labels = None if app_configs is None else {app.label for app in app_configs}
    loader = MigrationLoader(None, ignore_no_migrations=True)
    for (label, name), migration in sorted(loader.disk_migrations.items()):
        if labels is not None and label not in labels:
            continue
        for operation in migration.operations:
            if isinstance(operation, RemoveField) and operation.name == "_etag":
                yield Warning(
                    f"Migration {label}.{name} drops {operation.model_name}._etag in "
                    "one step, which breaks a rolling deploy",
                    hint=(
                        "Remove the field from the state first, and drop the column "
                        "in the next release: see the HTTP caching docs"
                    ),
                    obj=migration,
                    id="vng_api_common.caching.W001",
                )
