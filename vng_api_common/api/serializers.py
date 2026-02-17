from rest_framework import serializers

from ..models import JWTSecret


class JWTSecretSerializer(serializers.ModelSerializer):
    class Meta:  # type: ignore
        model = JWTSecret
        fields = ("identifier", "secret")
