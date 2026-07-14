from kaji.core.config import Settings as SDKSettings
from kaji_serve.config import Settings


def test_sdk_settings_exclude_service_infrastructure() -> None:
    sdk_settings = SDKSettings()

    for name in ("DATABASE_URL", "SUPABASE_ANON_KEY", "JWT_SECRET", "SONIOX_API_KEY"):
        assert not hasattr(sdk_settings, name)


def test_service_settings_extend_sdk_and_resolve_aliases() -> None:
    settings = Settings(
        SUPABASE_URL="https://supabase.test",
        SUPABASE_SERVICE_KEY="service-key",
        JWT_ISSUER="https://supabase.test/auth/v1",
        JWT_AUDIENCE="authenticated",
        CORS_ALLOW_ORIGINS="",
    )

    assert settings.KAJI_MODEL_PROVIDER == "mock"
    assert settings.SUPABASE_KONG_URL == "https://supabase.test"
    assert settings.SUPABASE_SERVICE_ROLE_KEY == "service-key"
    assert settings.JWT_ISSUER == "https://supabase.test/auth/v1"
    assert settings.JWT_AUDIENCE == "authenticated"
    assert settings.cors_allow_origins == ["http://localhost:3000"]
