"""
Test that the required content type headers are present.
"""

from django.urls import path

kk
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from tests import generate_schema


class JSONView(APIView):
    renderer_classes = (JSONRenderer,)
    parser_classes = (JSONParser,)

    def get(self, request):
        return Response({})

    def post(self, request):
        return Response({})


urlpatterns = [
    path("json", JSONView.as_view(), name="json"),
]


def _generate_schema():
    return generate_schema(urlpatterns)


def test_json_content_type():
    schema = _generate_schema()

    get_operation = schema["paths"]["/json"]["get"]
    post_operation = schema["paths"]["/json"]["post"]

    assert get_operation.get("parameters", []) == []
    assert post_operation["parameters"] == [
        {
            "description": "Content type of the request body.",
            "in": "header",
            "name": "Content-Type",
            "required": True,
            "schema": {"enum": ["application/json"], "type": "string"},
        }
    ]
