from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str  = "ลานสุข POS"
    DEBUG:    bool = True
    SECRET_KEY: str = "change-me-in-production"

    DATABASE_URL: str = "sqlite+aiosqlite:///./lansook.db"

    TELEGRAM_BOT_TOKEN:      str = ""
    TELEGRAM_WEBHOOK_SECRET: str = "change-me"
    ADMIN_CHAT_ID:           int = 0
    GROUP_CHAT_ID:           int = -5111246315

    QR_SECRET_KEY:     str = "qr-secret-change-me"
    QR_EXPIRE_MINUTES: int = 480

    PRINTER_IP:   str = "192.168.1.200"
    PRINTER_PORT: int = 9100

    RESTAURANT_LAT:    float = 15.2448
    RESTAURANT_LON:    float = 104.8473
    GPS_RADIUS_METERS: float = 200.0

    DEFAULT_FREE_LATE_PER_MONTH: int   = 3
    DEFAULT_FINE_PER_MINUTE:     float = 5.0
    DEFAULT_GRACE_MINUTES:       int   = 5
    OT_RATE_MULTIPLIER:          float = 1.5


settings = Settings()
