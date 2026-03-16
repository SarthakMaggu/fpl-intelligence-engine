from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    ENVIRONMENT: str = "development"
    BACKEND_PORT: int = 8000
    FRONTEND_URL: str = "http://localhost:3001"
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    PUBLIC_APP_URL: str = "http://localhost:8000"
    ADMIN_TOKEN: str = ""

    # Database — Railway injects postgres:// which asyncpg needs as postgresql+asyncpg://
    DATABASE_URL: str = "postgresql+asyncpg://postgres:changeme@localhost:5433/fpl_intelligence"
    POSTGRES_PASSWORD: str = "changeme"

    # Redis
    REDIS_URL: str = "redis://localhost:6380/0"
    JOB_QUEUE_KEY: str = "jobs:queue"

    # FPL
    FPL_TEAM_ID: int = 0
    UNDERSTAT_SEASON: str = "2025"
    USER_CAP: int = 500
    ANONYMOUS_SESSION_TTL_HOURS: int = 24
    ANALYSIS_CACHE_TTL_SECONDS: int = 60
    PREDICTION_CACHE_TTL_SECONDS: int = 600
    FIXTURE_CACHE_TTL_SECONDS: int = 3600
    MAX_REQUESTS_PER_MINUTE: int = 120
    MAX_HEAVY_REQUESTS_PER_DAY: int = 10
    FEATURE_DRIFT_THRESHOLD: float = 0.2
    WORKER_POLL_INTERVAL_MS: int = 1500
    DECISION_ENGINE_MODE: str = "shadow"
    DEFAULT_RISK_PROFILE: str = "balanced"
    DECISION_ENGINE_FREEZE_SNAPSHOTS: bool = True

    # Reddit
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_USER_AGENT: str = "FPLIntelligenceBot/1.0"

    # The Odds API
    ODDS_API_KEY: str = ""

    # SendGrid
    SENDGRID_API_KEY: str = ""
    SENDGRID_FROM_EMAIL: str = ""
    NOTIFICATION_TO_EMAIL: str = ""
    # Admin alert email — receives pipeline failure notifications
    ADMIN_ALERT_EMAIL: str = ""

    # Twilio WhatsApp
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WHATSAPP_FROM: str = "whatsapp:+14155238886"
    TWILIO_WHATSAPP_TO: str = ""

    @property
    def async_database_url(self) -> str:
        """Return DATABASE_URL with the asyncpg driver.
        Railway (and many hosts) inject a plain postgres:// URL — convert it."""
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = "postgresql+asyncpg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = "postgresql+asyncpg://" + url[len("postgresql://"):]
        return url

    @property
    def cors_origins(self) -> list[str]:
        """FRONTEND_URL may be comma-separated (e.g. Vercel + custom domain)."""
        base = ["http://localhost:3001", "http://localhost:3000"]
        for origin in self.FRONTEND_URL.split(","):
            origin = origin.strip()
            if origin and origin not in base:
                base.append(origin)
        return base

    @property
    def email_enabled(self) -> bool:
        return bool(self.SENDGRID_API_KEY and self.SENDGRID_FROM_EMAIL)

    @property
    def whatsapp_enabled(self) -> bool:
        return bool(self.TWILIO_ACCOUNT_SID and self.TWILIO_WHATSAPP_TO)

    @property
    def odds_enabled(self) -> bool:
        return bool(self.ODDS_API_KEY)

    @property
    def reddit_enabled(self) -> bool:
        return bool(self.REDDIT_CLIENT_ID and self.REDDIT_CLIENT_SECRET)


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
