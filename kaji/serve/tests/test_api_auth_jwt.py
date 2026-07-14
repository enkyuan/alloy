from unittest.mock import patch

import pytest
from fastapi import HTTPException
from jose import jwt

from kaji_serve.config import settings
from kaji_serve.server.auth_utils import decode_bearer_token

ISSUER = "https://test.supabase.co/auth/v1"
AUDIENCE = "authenticated"
SECRET = "test-jwt-secret"


@pytest.fixture(autouse=True)
def configured_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "JWT_SECRET", SECRET)
    monkeypatch.setattr(settings, "JWT_ISSUER", ISSUER)
    monkeypatch.setattr(settings, "JWT_AUDIENCE", AUDIENCE)


def encode_token(**claims: str) -> str:
    return jwt.encode(
        {"sub": "user-1", "iss": ISSUER, "aud": AUDIENCE, **claims},
        SECRET,
        algorithm="HS256",
    )


def test_decode_bearer_token_validates_expected_claims() -> None:
    payload = decode_bearer_token(encode_token())

    assert payload["id"] == "user-1"


@pytest.mark.parametrize(
    ("claim", "value"),
    [("iss", "https://malicious.example"), ("aud", "another-service")],
)
def test_decode_bearer_token_rejects_wrong_issuer_or_audience(
    claim: str, value: str
) -> None:
    with pytest.raises(HTTPException) as error:
        decode_bearer_token(encode_token(**{claim: value}))

    assert error.value.status_code == 401


@pytest.mark.parametrize("missing_claim", ["iss", "aud"])
def test_decode_bearer_token_requires_issuer_and_audience_claims(
    missing_claim: str,
) -> None:
    claims = {"sub": "user-1", "iss": ISSUER, "aud": AUDIENCE}
    claims.pop(missing_claim)
    token = jwt.encode(claims, SECRET, algorithm="HS256")

    with pytest.raises(HTTPException) as error:
        decode_bearer_token(token)

    assert error.value.status_code == 401


def test_decode_bearer_token_rejects_forged_empty_key_before_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forged = jwt.encode(
        {"sub": "attacker", "iss": ISSUER, "aud": AUDIENCE},
        "",
        algorithm="HS256",
    )
    monkeypatch.setattr(settings, "JWT_SECRET", "   ")

    with patch("jose.jwt.decode") as decode:
        with pytest.raises(HTTPException) as error:
            decode_bearer_token(forged)

    assert error.value.status_code == 503
    decode.assert_not_called()


@pytest.mark.parametrize("setting_name", ["JWT_ISSUER", "JWT_AUDIENCE"])
def test_decode_bearer_token_requires_claim_configuration_before_decode(
    monkeypatch: pytest.MonkeyPatch, setting_name: str
) -> None:
    monkeypatch.setattr(settings, setting_name, "")

    with patch("jose.jwt.decode") as decode:
        with pytest.raises(HTTPException) as error:
            decode_bearer_token(encode_token())

    assert error.value.status_code == 503
    decode.assert_not_called()
