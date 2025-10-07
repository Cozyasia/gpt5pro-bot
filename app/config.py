from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    BOT_TOKEN: str
    PUBLIC_URL: str        # полный https://...onrender.com
    WEBHOOK_SECRET: str    # любой ваш секретный путь, например '9b12d...'

settings = Settings()
