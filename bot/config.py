from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        # Старые .env могут содержать PRIVATE_CHANNEL_ID и т.п. — не падаем на них.
        extra="ignore",
    )

    bot_token: str
    main_channel_id: int
    main_channel_link: str
    admin_ids: str = ""
    db_path: str = "data/bot.db"

    # Чат (группа/канал), куда бот пересылает заявки на проекты вместе с файлами.
    # Если не задан — заявки приходят всем админам в личку.
    applications_chat_id: int | None = None

    @property
    def admin_id_list(self) -> list[int]:
        return [int(x) for x in self.admin_ids.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
