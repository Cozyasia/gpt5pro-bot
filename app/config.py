from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AnyUrl
import os

class Settings(BaseSettings):
    BOT_TOKEN: str = Field(..., description="Telegram bot token")
    PUBLIC_URL: AnyUrl = Field(..., description="https://<subdomain>.onrender.com")
    WEBHOOK_SECRET: str = Field(..., description="Любая длинная строка для пути/секрета")
    PORT: int = Field(default_factory=lambda: int(os.getenv("PORT", "8000")),
                      description="Render подставит PORT")

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

settings = Settings()
