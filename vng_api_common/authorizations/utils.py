import time

import jwt


def generate_jwt(
    client_id: str,
    secret: str,
    user_id: str,
    user_representation: str,
    jwt_valid_for: int | None = None,
) -> str:
    iat = int(time.time())
    payload = {
        # standard claims
        "iss": client_id,
        "iat": iat,
        # custom claims
        "client_id": client_id,
        "user_id": user_id,
        "user_representation": user_representation,
    }
    if jwt_valid_for:
        payload["exp"] = iat + jwt_valid_for

    token = jwt.encode(payload, secret, algorithm="HS256")
    return f"Bearer {token}"
