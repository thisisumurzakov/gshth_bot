from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    bot_token: str
    main_channel_id: int
    main_channel_link: str
    private_channel_id: int
    admin_ids: str = ""
    db_path: str = "data/bot.db"

    referral_goal: int = 3

    @property
    def admin_id_list(self) -> list[int]:
        return [int(x) for x in self.admin_ids.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
