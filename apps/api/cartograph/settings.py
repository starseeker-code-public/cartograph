from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://cartograph:cartograph@localhost:5432/cartograph"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

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


settings = Settings()
