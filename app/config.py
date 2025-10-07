from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    BOT_TOKEN: str
    MODE: str = Field(default="webhook")  # webhook | polling
    WEBHOOK_SECRET: str = Field(default="change-me")
    RENDER_EXTERNAL_URL: str | None = None  # Render проставит автоматически
    PORT: int = 10000

    @property
    def webhook_url(self) -> str:
        base = self.RENDER_EXTERNAL_URL or ""
        # конечная точка, например https://xxx.onrender.com/tg/<secret>
        return base.rstrip("/") + f"/tg/{self.WEBHOOK_SECRET}"

settings = Settings()
