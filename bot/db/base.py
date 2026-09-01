from pathlib import Path

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


async def create_schema(engine) -> None:
    from bot.db import models  # noqa: F401  (регистрация моделей в metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
