"""
A deploy can change representations without writing a row, so a stored ETag must
not outlive the code it was calculated with.

Releases that represent resources differently differ in the setting
``ETAG_REPRESENTATION_VERSION``; Open Zaak sets it to its release. The new release
here changes what a ``SerializerMethodField`` returns, which no introspection of
the serializers could notice. During a rolling deploy, the old and the new
release serve side by side from one database.

The domain and scheme of hyperlinks come from settings the library reads itself,
so changing them needs no new version.
"""

from collections.abc import Callable

from django.test import Client

import pytest
from pytest_django import Settings

from testapp.models import Folder, Sheet
from testapp.serializers import FolderSerializer

from .etags import ServedBodies, assert_served_etags_match, current_etag

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


def test_old_and_new_release_side_by_side(
    client: Client, deploy: Deploy, folder: Folder, served: ServedBodies
) -> None:
    assert_served_etags_match(client, served)
    deploy("1.1.0")
    assert_served_etags_match(client, served)
    deploy("1.0.0")  # an old instance, after a new one served
    assert_served_etags_match(client, served)
    deploy("1.1.0")  # a new instance, after an old one served again
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
