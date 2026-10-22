"""
A deploy can change representations without writing a row, so a stored ETag must
not outlive the code it was calculated with.

Releases that represent resources differently differ in the setting
``ETAG_REPRESENTATION_VERSION``; Open Zaak sets it to its release. A release of
this library needs no setting. The new release
here changes what a ``SerializerMethodField`` returns, which no introspection of
the serializers could notice. After a rollback, the release before serves from
the same database again.

The domain and scheme of hyperlinks come from settings the library reads itself,
so changing them needs no new version.
"""

from collections.abc import Callable

from django.test import Client

import pytest
from pytest_django import Settings

import vng_api_common
from testapp.models import Folder, Sheet
from testapp.serializers import FolderSerializer

from .etags import (
    ServedBodies,
    assert_served_etags_match,
    current_etag,
    forget_stored_etags,
)

pytestmark = pytest.mark.django_db(transaction=True)


def first_sheet_title_in_capitals(self: FolderSerializer, obj: Folder) -> str:
    first = obj.sheets.first()
    return first.title.upper() if first else ""


# how each release represents a folder's first sheet title
RELEASES: dict[str, Callable[[FolderSerializer, Folder], str]] = {
    "1.0.0": FolderSerializer.get_first_sheet_title,
    "1.1.0": first_sheet_title_in_capitals,
}

type Deploy = Callable[[str], None]


@pytest.fixture
def deploy(
    etag_api: None, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Deploy:
    """Run the code and settings of a release, starting with 1.0.0."""

    def run(release: str) -> None:
        method = RELEASES[release]
        monkeypatch.setattr(FolderSerializer, "get_first_sheet_title", method)
        settings.ETAG_REPRESENTATION_VERSION = release

    run("1.0.0")
    return run


@pytest.fixture
def served() -> ServedBodies:
    """The bodies served under each ETag, across releases."""
    return ServedBodies()


@pytest.fixture
def folder(etag_api: None) -> Folder:
    folder = Folder.objects.create(name="a", code="a")
    Sheet.objects.create(folder=folder, title="a", position=0)
    return folder


def test_a_new_release_serves_etags_of_its_representations(
    client: Client, deploy: Deploy, folder: Folder, served: ServedBodies
) -> None:
    assert_served_etags_match(client, served)
    etag = current_etag(Folder, folder.pk)

    deploy("1.1.0")

    assert current_etag(Folder, folder.pk) != etag, "not another representation"
    assert_served_etags_match(client, served)


def test_a_rollback_and_a_redeploy(
    client: Client, deploy: Deploy, folder: Folder, served: ServedBodies
) -> None:
    assert_served_etags_match(client, served)
    deploy("1.1.0")
    assert_served_etags_match(client, served)
    deploy("1.0.0")  # rolled back, after the new release served
    assert_served_etags_match(client, served)
    deploy("1.1.0")  # deployed again, after the old release served again
    assert_served_etags_match(client, served)


def test_an_upgrade_of_this_library_serves_etags_of_its_representations(
    client: Client,
    folder: Folder,
    served: ServedBodies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert_served_etags_match(client, served)
    etag = current_etag(Folder, folder.pk)

    # the project's release, and so ETAG_REPRESENTATION_VERSION, stays
    monkeypatch.setattr(vng_api_common, "__version__", "99.0.0")
    monkeypatch.setattr(
        FolderSerializer, "get_first_sheet_title", first_sheet_title_in_capitals
    )

    assert current_etag(Folder, folder.pk) != etag, "not another representation"
    assert_served_etags_match(client, served)


def test_the_upgrade_serves_etags_of_existing_data(
    client: Client, folder: Folder, served: ServedBodies
) -> None:
    forget_stored_etags()  # as the migration leaves data written before it

    assert_served_etags_match(client, served)


def test_a_new_domain_serves_etags_of_its_hyperlinks(
    client: Client, settings: Settings, folder: Folder, served: ServedBodies
) -> None:
    assert_served_etags_match(client, served)
    etag = current_etag(Folder, folder.pk)

    settings.SITE_DOMAIN = "zaken.example.org"
    settings.IS_HTTPS = True

    assert current_etag(Folder, folder.pk) != etag, "not another representation"
    assert_served_etags_match(client, served)


def test_without_the_setting(
    client: Client, settings: Settings, folder: Folder, served: ServedBodies
) -> None:
    del settings.ETAG_REPRESENTATION_VERSION  # not every project imports conf.api

    assert_served_etags_match(client, served)


def test_old_migrations_can_disconnect_the_old_receiver(
    client: Client, folder: Folder, served: ServedBodies
) -> None:
    from django.db.models.signals import post_save

    from vng_api_common.caching.signals import (
        mark_related_instances_for_etag_update as old_receiver,
    )

    # as Open Zaak's zaken/0017 does around its data migration
    post_save.disconnect(old_receiver, sender=None)
    folder.save()
    post_save.connect(old_receiver, sender=None)
    folder.save()

    assert_served_etags_match(client, served)
