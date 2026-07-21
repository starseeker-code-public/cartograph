from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Placeholder keys that must never sign tokens outside debug mode.
_PLACEHOLDER_SECRETS = {"change-me-in-production", "change-me", "changeme", "secret", ""}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://cartograph:cartograph@localhost:5433/cartograph"

    # Redis
    redis_url: str = "redis://localhost:6380/0"

    # API
    api_prefix: str = "/api"
    debug: bool = False

    # Auth (Argon2id / JWT)
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 60 * 24  # 1 day

    # Tile cache TTL (seconds)
    tile_cache_ttl: int = 300
    eta_cache_ttl: int = 3600

    # Geofences
    geofence_dwell_seconds: int = 600
    # GPS fixes with worse accuracy than this don't trigger geofence events.
    geofence_accuracy_max_m: float = 100.0
    # Per-driver ceiling on location updates (the device is the source).
    location_rate_limit_per_minute: int = 120

    @model_validator(mode="after")
    def _reject_placeholder_secret(self) -> "Settings":
        """A known/weak signing key in non-debug mode is full auth bypass —
        anyone can forge JWTs for any tenant. Refuse to start."""
        if not self.debug and (
            self.secret_key.lower() in _PLACEHOLDER_SECRETS or len(self.secret_key) < 16
        ):
            raise ValueError(
                "SECRET_KEY is a placeholder or too short (<16 chars). "
                "Generate one with `openssl rand -hex 32` and set it in the "
                "environment, or set DEBUG=true for local development."
            )
        return self


settings = Settings()
