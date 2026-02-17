from typing import TYPE_CHECKING

from django.http import HttpResponseBase

from rest_framework import status

if TYPE_CHECKING:
    from rest_framework.test import APITestCase as _Base
else:
    _Base = object


class CacheMixin(_Base):
    def assertHasETag(self, response: HttpResponseBase, status_code=status.HTTP_200_OK):
        self.assertEqual(response.status_code, status_code)
        self.assertIn("ETag", response)
        self.assertNotEqual(response["ETag"], "")

    def assertHeadHasETag(self, url: str, status_code=status.HTTP_200_OK, **extra):
        response = self.client.head(url, **extra)

        self.assertHasETag(response)

        # head requests should not return a response body, only headers
        self.assertEqual(response.content, b"")
