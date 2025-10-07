from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyUrl

class Settings(BaseSettings):
    BOT_TOKEN: str
    WEBHOOK_SECRET: str          # любая длинная строка без пробелов, ≥16 символов
    PUBLIC_URL: AnyUrl           # https://<твой-сабдомен>.onrender.com
    PORT: int = 10000            # запасной порт, Render подставит свой через env PORT

    model_config = SettingsConfigDict(env_file='.env', case_sensitive=True)

settings = Settings()
