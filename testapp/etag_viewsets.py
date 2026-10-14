"""
Viewsets for the ETag tests (tests/test_etag_*.py), routed in testapp.etag_urls.

``expand_param`` names the query parameter that expands related resources (see
``ExpandingSerializer``): ``expand`` as in Open Zaak, or ``include`` as in
djangorestframework-inclusions. ``conditional_retrieve`` learns that it selects
another representation from ``variant_params``.
"""

from collections.abc import Set as AbstractSet

from django.http import HttpRequest

from rest_framework import permissions, viewsets

from vng_api_common.caching import conditional_retrieve

from .models import Folder, Sheet, Shortcut, Tag
from .serializers import (
    FolderSerializer,
    SheetSerializer,
    ShortcutSerializer,
    TagSerializer,
)


def allowed_codes(request: HttpRequest) -> AbstractSet[str] | None:
    """
    The codes of the folders the client may see, given in ``X-Allowed-Codes``; all
    of them without it. A stand-in for the authorizations of Open Zaak's clients.
    """
    header = request.headers.get("X-Allowed-Codes")
    return None if header is None else frozenset(header.split(","))


class InAllowedFolder(permissions.BasePermission):
    def has_object_permission(self, request, view, obj) -> bool:  # type: ignore[override]
        codes = allowed_codes(request)
        return codes is None or obj.folder.code in codes


@conditional_retrieve(
    extra_depends_on={"sheets"},  # first_sheet_title
    variant_params={"expand"},
)
class FolderViewSet(viewsets.ReadOnlyModelViewSet):
    """A folder the client may not see is not found, like a zaak out of scope."""

    queryset = Folder.objects.all()
    serializer_class = FolderSerializer
    expand_param = "expand"

    def get_queryset(self):
        queryset = super().get_queryset()
        if (codes := allowed_codes(self.request)) is not None:
            queryset = queryset.filter(code__in=codes)
        return queryset


@conditional_retrieve(variant_params={"include"})
class SheetViewSet(viewsets.ReadOnlyModelViewSet):
    """A sheet in a folder the client may not see is forbidden."""

    queryset = Sheet.objects.all()
    serializer_class = SheetSerializer
    permission_classes = [InAllowedFolder]
    expand_param = "include"


@conditional_retrieve(variant_params={"expand"})
class TagViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    expand_param = "expand"


@conditional_retrieve(variant_params={"include"})
class ShortcutViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Shortcut.objects.all()
    serializer_class = ShortcutSerializer
    expand_param = "include"
