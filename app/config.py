from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    BOT_TOKEN: str
    WEBHOOK_SECRET: str           # любая длинная строка, см. ниже пример
    PUBLIC_URL: str               # строка, БЕЗ завершающего '/'

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
