from unittest.mock import Mock, patch

from django.core.checks import Tags
from django.core.checks.registry import registry
from django.db import migrations
from django.db.migrations.operations.base import Operation

import pytest

from vng_api_common.caching.checks import check_etag_column_drops
from vng_api_common.checks import enum_value_ok


@pytest.mark.parametrize(
    "value",
    ["CAPS", "PartialCaps", "dash-instead-of-underscore", "non_áscii_character"],
)
def test_invalid_enum_values(value: str):
    assert enum_value_ok(value) is False


@pytest.mark.parametrize(
    "value", ["lowercased", "dashes_in_word", "a_number_0_is_okay"]
)
def test_valid_enum_values(value: str):
    assert enum_value_ok(value) is True


def drops(*operations: Operation) -> list[str]:
    """The warnings for a migration of the testapp with ``operations``."""
    migration = migrations.Migration("0099_drop_etag", "testapp")
    migration.operations = list(operations)
    loader = Mock(disk_migrations={("testapp", migration.name): migration})
    with patch("vng_api_common.caching.checks.MigrationLoader", return_value=loader):
        return [warning.id for warning in check_etag_column_drops(None)]


def test_a_plain_drop_of_etag_warns():
    assert drops(migrations.RemoveField("person", "_etag")) == [
        "vng_api_common.caching.W001"
    ]


def test_a_drop_of_etag_from_the_state_only_does_not_warn():
    assert (
        drops(
            migrations.SeparateDatabaseAndState(
                state_operations=[migrations.RemoveField("person", "_etag")]
            ),
            migrations.RemoveField("person", "name"),
        )
        == []
    )


def test_the_migrations_drop_no_etag_in_one_step():
    assert list(check_etag_column_drops(None)) == []


def test_migrate_runs_the_check():
    assert check_etag_column_drops in registry.registered_checks
    assert Tags.database in check_etag_column_drops.tags
