from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def make_engine(db_path: str):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return create_async_engine(f"sqlite+aiosqlite:///{db_path}")


def make_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


# Колонки, добавленные в users после первой версии бота. create_all не меняет
# существующие таблицы, поэтому на старой базе дописываем их сами.
_NEW_USER_COLUMNS = {
    "username": "VARCHAR(64)",
    "birth_date": "DATE",
    "workplace": "VARCHAR(255)",
    "subscribed_at": "DATETIME",
}


def _upgrade_users_table(conn) -> None:
    existing = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
    for name, sql_type in _NEW_USER_COLUMNS.items():
        if name not in existing:
            conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {sql_type}"))
    if "subscribed_at" not in existing and "invite_link" in existing:
        # В старой версии персональная ссылка выдавалась только после проверки подписки.
        conn.execute(
            text(
                "UPDATE users SET subscribed_at = created_at "
                "WHERE invite_link IS NOT NULL"
            )
        )


async def create_schema(engine) -> None:
    from bot.db import models  # noqa: F401  (регистрация моделей в metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_upgrade_users_table)
