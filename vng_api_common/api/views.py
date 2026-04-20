import warnings

from rest_framework.generics import CreateAPIView

from ..models import JWTSecret
from ..scopes import Scope
from .permissions import JWTCreatePermission
from .serializers import JWTSecretSerializer


class CreateJWTSecretView(CreateAPIView):
    """
    XXX: deprecated, scheduled for removal in 3.0.

    The zds-token-issuer is no longer used, and maintained implementations
    no longer rely on this view.
    """

    action = "create"
    swagger_schema = None

    model = JWTSecret
    serializer_class = JWTSecretSerializer
    permission_classes = (JWTCreatePermission,)
    required_scopes = {
        "create": Scope("autorisaties.credentials-registreren", private=True)
    }

    @classmethod
    def as_view(cls, **initkwargs):
        warnings.warn(
            "The 'jwtsecret/' endpoint and CreateJWTSecretView are deprecated "
            "and scheduled for removal in 3.0.",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return super().as_view(**initkwargs)
