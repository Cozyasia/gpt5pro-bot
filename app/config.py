from pydantic import BaseSettings, Field

class Settings(BaseSettings):
    BOT_TOKEN: str
    PUBLIC_URL: str                     # https://<твой-сервис>.onrender.com  (без хвостового /)
    WEBHOOK_SECRET: str = Field(min_length=1)  # любой секрет, см. ниже
    PORT: int = 8000                    # Render подставит свой PORT из env

    class Config:
        extra = "ignore"

settings = Settings()
