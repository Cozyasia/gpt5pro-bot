import os
from pydantic import AnyUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    BOT_TOKEN: str
    WEBHOOK_SECRET: str
    PUBLIC_URL: AnyUrl           # https://gpt5pro-bot.onrender.com
    # Render сам кладёт порт в env PORT → подхватываем его
    PORT: int = Field(default_factory=lambda: int(os.getenv("PORT", "10000")))

    model_config = SettingsConfigDict(
        env_prefix="",            # имена env = имена полей (BOT_TOKEN, ...)
        case_sensitive=True
    )

settings = Settings()
