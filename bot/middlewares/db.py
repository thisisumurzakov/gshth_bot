from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db import repo


class DbSessionMiddleware(BaseMiddleware):
    """Открывает сессию БД на каждый апдейт и кладёт её в data["session"]."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            return await handler(event, data)


class UserMiddleware(BaseMiddleware):
    """Подгружает зарегистрированного пользователя и его язык (message/callback)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session = data["session"]
        from_user = getattr(event, "from_user", None)
        user = await repo.get_user(session, from_user.id) if from_user else None
        # Пустая строка — «username нет»; NULL — «ещё не проверяли».
        if user is not None and user.username != (from_user.username or ""):
            # Пишем в базу только когда username появился, сменился или пропал.
            user.username = from_user.username or ""
            await session.commit()
        data["user"] = user
        data["lang"] = user.language if user else None
        return await handler(event, data)
