from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    BOT_TOKEN: str
    PUBLIC_URL: str           # например: https://gpt5pro-bot.onrender.com  (без хвостового '/')
    WEBHOOK_SECRET: str       # любой длинный slug, например: 9b12d3200a…
    PORT: int = Field(default=8000)   # Render подставит свой $PORT

    # читаем только из переменных окружения Render
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

settings = Settings()
