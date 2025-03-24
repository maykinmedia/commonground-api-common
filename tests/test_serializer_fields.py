from dateutil.relativedelta import relativedelta
from rest_framework import serializers, viewsets

from vng_api_common.serializers import DurationField


class DurationSerializer(serializers.Serializer):
    duration = DurationField()


class DurationView(viewsets.ModelViewSet):
    serializer_class = DurationSerializer


def test_duration_field_internal_data():
    data = {"duration": "P10D"}
    serializer = DurationSerializer(data=data)
    assert serializer.is_valid()
    assert serializer.to_internal_value(data) == {"duration": relativedelta(days=+10)}


def test_duration_to_representation():
    data = {"duration": "P10D"}
    serializer = DurationSerializer(data=data)
    assert serializer.is_valid()
    assert serializer.to_representation({"duration": relativedelta(days=+10)}) == data


def test_valid_duration_field():
    duration_options = [
        "P10D",
        "P1M10D",
        "P1Y1M10D",
        "P-10D",
        "P-1M-10D",
        "P-1Y-1M-10D",
        "P1Y-1M10D",
    ]


def test_valid_duration_field():
    duration_options = [
        ("P10D", relativedelta(days=10)),
        ("P1M10D", relativedelta(months=1, days=10)),
        ("P1Y1M10D", relativedelta(years=1, months=1, days=10)),
        ("P-10D", relativedelta(days=-10)),
        ("P-1M-10D", relativedelta(months=-1, days=-10)),
        ("P-1Y-1M-10D", relativedelta(years=-1, months=-1, days=-10)),
        ("P1Y-1M10D", relativedelta(years=+1, months=-1, days=+10)),
    ]
    data = {"duration": ""}
    for duration in duration_options:
        data["duration"] = duration[0]
        serializer = DurationSerializer(data=data)
        assert serializer.is_valid()
        assert serializer.to_internal_value(data) == {"duration": duration[1]}


def test_invalid_duration_field():
    duration_options = [
        "test",
        "10D",
        "-P10D",
        "-P-10D",
    ]
    data = {"duration": ""}

    for d in duration_options:
        data["duration"] = d
        serializer = DurationSerializer(data=data)
        assert not serializer.is_valid()
        assert (
            serializer.errors["duration"][0]
            == "Duration has wrong format. Use one of these formats instead: P(n)Y(n)M(n)D."
        )
