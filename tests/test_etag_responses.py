"""
Which responses carry an ETag, and which conditional GETs get a 304.

The stored ETag validates one representation of a resource: the one
``calculate_etag`` serializes. A request with a query parameter declared in
``conditional_retrieve(variant_params=...)`` selects another representation, so
its response carries no ETag and is never a 304. Open Zaak's ``expand`` is the
well-known example; half the testapp's viewsets call it ``include``, so the
library can only know these parameters from the declaration.

A client that may not see a resource gets the same 404 or 403 whether or not its
GET is conditional, and no ETag: a 304 would tell it that the resource exists and
is unchanged.

A HEAD is answered as its GET is, without the body.
"""

from collections.abc import Callable

from django.db.models import Model
from django.http import HttpResponse
from django.test import Client

import pytest

from testapp.models import Folder, Sheet, Shortcut, Tag

from .etags import RESOURCES, current_etag, detail_url

pytestmark = pytest.mark.django_db(transaction=True)

# the request methods that are answered with an ETag
send_with = pytest.mark.parametrize(
    "send", [Client.get, Client.head], ids=lambda send: send.__name__.upper()
)

# how a sheet, tag or shortcut refers to its folder
FOLDER_LOOKUPS: dict[type[Model], str] = {
    Sheet: "folder",
    Tag: "folders",
    Shortcut: "target",
}


@pytest.fixture
def folders(etag_api: None) -> tuple[Folder, Folder]:
    """Folders with codes "a" and "b", each with a sheet, a tag and a shortcut."""
    pair = (
        Folder.objects.create(name="a", code="a"),
        Folder.objects.create(name="b", code="b"),
    )
    for folder in pair:
        Sheet.objects.create(folder=folder, title=folder.name, position=0)
        Tag.objects.create(label=folder.name).folders.add(folder)
        Shortcut.objects.create(label=folder.name, target=folder)
    return pair


def in_folder(model: type[Model], folder: Folder) -> Model:
    """The folder itself, or its sheet, tag or shortcut."""
    if model is Folder:
        return folder
    return model._default_manager.get(**{FOLDER_LOOKUPS[model]: folder})


@send_with
@pytest.mark.parametrize(
    ("model", "query"),
    [
        (Folder, "expand=sheets"),
        (Folder, "expand=tags,sheets"),
        (Sheet, "include=folder"),
        (Tag, "expand=folders"),
        (Shortcut, "include=target"),
    ],
)
def test_a_variant_gets_no_etag_and_no_304(
    client: Client,
    folders: tuple[Folder, Folder],
    send: Callable[..., HttpResponse],
    model: type[Model],
    query: str,
) -> None:
    pk = in_folder(model, folders[0]).pk
    url = detail_url(model, pk)

    variant = send(
        client, f"{url}?{query}", headers={"If-None-Match": current_etag(model, pk)}
    )

    assert variant.status_code == 200
    assert not variant.has_header("ETag")
    # a HEAD has no body to compare
    assert client.get(f"{url}?{query}").json() != client.get(url).json(), (
        "not another representation"
    )


@send_with
@pytest.mark.parametrize("if_none_match", ["current ETag", "*"])
@pytest.mark.parametrize(("model", "status"), [(Folder, 404), (Sheet, 403)])
def test_no_304_or_etag_for_what_the_client_may_not_see(
    client: Client,
    folders: tuple[Folder, Folder],
    send: Callable[..., HttpResponse],
    model: type[Model],
    status: int,
    if_none_match: str,
) -> None:
    pk = in_folder(model, folders[1]).pk
    condition = current_etag(model, pk) if if_none_match == "current ETag" else "*"

    response = send(
        client,
        detail_url(model, pk),
        headers={"X-Allowed-Codes": "a", "If-None-Match": condition},
    )

    assert (response.status_code, response.has_header("ETag")) == (status, False)


@send_with
@pytest.mark.parametrize("model", [Folder, Sheet])
def test_a_304_for_what_the_client_may_see(
    client: Client,
    folders: tuple[Folder, Folder],
    send: Callable[..., HttpResponse],
    model: type[Model],
) -> None:
    pk = in_folder(model, folders[0]).pk
    etag = current_etag(model, pk)

    response = send(
        client,
        detail_url(model, pk),
        headers={"X-Allowed-Codes": "a", "If-None-Match": etag},
    )

    assert (response.status_code, response["ETag"]) == (304, etag)


@pytest.mark.parametrize("model", list(RESOURCES))
def test_a_head_gets_the_etag_of_its_get_and_no_body(
    client: Client, folders: tuple[Folder, Folder], model: type[Model]
) -> None:
    pk = in_folder(model, folders[0]).pk
    url = detail_url(model, pk)

    head = client.head(url)

    assert (head.status_code, head["ETag"]) == (200, current_etag(model, pk))
    assert head.content == b""
    assert client.get(url).content, "a GET has a body"
