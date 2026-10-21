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

A GET with an ``If-Match`` that doesn't list the current ETag gets a 412, and the
comparison is strong: ``W/`` and the current ETag is no match.

A HEAD is answered as its GET is, without the body.
"""

from collections.abc import Callable
from contextlib import nullcontext

from django.db import transaction
from django.db.models import Model
from django.http import HttpResponse
from django.test import Client

import pytest

from testapp.models import Folder, Sheet, Shortcut, Tag

from .etags import (
    RESOURCES,
    ServedBodies,
    assert_served_etags_match,
    current_etag,
    detail_url,
    forget_stored_etags,
)

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
@pytest.mark.parametrize("if_none_match", ["current ETag", "*"])
@pytest.mark.parametrize("model", [Folder, Sheet])
def test_a_304_for_what_the_client_may_see(
    client: Client,
    folders: tuple[Folder, Folder],
    send: Callable[..., HttpResponse],
    model: type[Model],
    if_none_match: str,
) -> None:
    pk = in_folder(model, folders[0]).pk
    etag = current_etag(model, pk)
    condition = etag if if_none_match == "current ETag" else "*"

    response = send(
        client,
        detail_url(model, pk),
        headers={"X-Allowed-Codes": "a", "If-None-Match": condition},
    )

    assert (response.status_code, response["ETag"]) == (304, etag)


@send_with
@pytest.mark.parametrize("if_match", ['"another"', "weak current ETag"])
@pytest.mark.parametrize("model", [Folder, Sheet])
def test_a_412_for_an_if_match_without_the_current_etag(
    client: Client,
    folders: tuple[Folder, Folder],
    send: Callable[..., HttpResponse],
    model: type[Model],
    if_match: str,
) -> None:
    pk = in_folder(model, folders[0]).pk
    etag = current_etag(model, pk)
    condition = f"W/{etag}" if if_match == "weak current ETag" else if_match

    response = send(client, detail_url(model, pk), headers={"If-Match": condition})

    assert response.status_code == 412


@send_with
@pytest.mark.parametrize("if_match", ["current ETag", "*"])
@pytest.mark.parametrize("model", [Folder, Sheet])
def test_an_if_match_with_the_current_etag_is_served(
    client: Client,
    folders: tuple[Folder, Folder],
    send: Callable[..., HttpResponse],
    model: type[Model],
    if_match: str,
) -> None:
    pk = in_folder(model, folders[0]).pk
    etag = current_etag(model, pk)
    condition = f'"another", {etag}' if if_match == "current ETag" else "*"

    response = send(client, detail_url(model, pk), headers={"If-Match": condition})

    assert (response.status_code, response["ETag"]) == (200, etag)


@pytest.mark.parametrize(("model", "status"), [(Folder, 404), (Sheet, 403)])
def test_no_412_for_what_the_client_may_not_see(
    client: Client,
    folders: tuple[Folder, Folder],
    model: type[Model],
    status: int,
) -> None:
    pk = in_folder(model, folders[1]).pk

    response = client.get(
        detail_url(model, pk),
        headers={"X-Allowed-Codes": "a", "If-Match": '"another"'},
    )

    assert response.status_code == status


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


@pytest.mark.parametrize("enclosing", [False, True], ids=["autocommit", "atomic"])
@pytest.mark.parametrize("stored", ["none yet", "written since"])
def test_a_failed_fill_leaves_the_response(
    client: Client,
    folders: tuple[Folder, Folder],
    monkeypatch: pytest.MonkeyPatch,
    stored: str,
    enclosing: bool,
) -> None:
    folder = folders[0]
    if stored == "none yet":
        forget_stored_etags()
    else:
        folder.save()
    too_long = "f" * 33  # for the column: storing it fails in the database
    monkeypatch.setattr(
        "vng_api_common.caching.conditional.calculate_etag", lambda instance: too_long
    )

    with transaction.atomic() if enclosing else nullcontext():
        response = client.get(detail_url(Folder, folder.pk))
        assert Folder.objects.exists(), "the transaction is still usable"

    assert (response.status_code, response["ETag"]) == (200, f'"{too_long}"')
    monkeypatch.undo()
    assert_served_etags_match(client, ServedBodies())


def test_a_save_that_reorders_a_list(client: Client, etag_api: None) -> None:
    """A folder lists its shortcuts by label, without showing it."""
    folder = Folder.objects.create(name="a", code="a")
    first, _ = (Shortcut.objects.create(label=x, target=folder) for x in "ab")
    served = ServedBodies()
    assert_served_etags_match(client, served)

    first.label = "c"
    first.save(update_fields=["label"])

    assert_served_etags_match(client, served)
