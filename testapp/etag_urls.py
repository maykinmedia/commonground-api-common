"""
URLs for the ETag tests (tests/test_etag_*.py).

Kept apart from testapp.urls, so their endpoints stay out of the schema the other
tests generate.
"""

from django.urls import include, path

from vng_api_common import routers

from .etag_viewsets import FolderViewSet, SheetViewSet, ShortcutViewSet, TagViewSet

router = routers.DefaultRouter(trailing_slash=False)
router.register("folders", FolderViewSet)
router.register("sheets", SheetViewSet)
router.register("tags", TagViewSet)
router.register("shortcuts", ShortcutViewSet)

urlpatterns = [
    path("api/", include(router.urls)),
    path("ref/", include("vng_api_common.urls")),  # error responses link here
]
