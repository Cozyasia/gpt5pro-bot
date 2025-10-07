# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyHttpUrl

class Settings(BaseSettings):
    BOT_TOKEN: str
    WEBHOOK_SECRET: str
    PUBLIC_URL: AnyHttpUrl  # <-- вот это поле обязательно

    # читаем переменные окружения как есть (без префиксов)
    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        case_sensitive=True,
    )

settings = Settings()
