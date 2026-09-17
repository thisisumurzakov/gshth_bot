import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db import repo
from bot.services.broadcast import SEND_INTERVAL

logger = logging.getLogger(__name__)


async def backfill_usernames(
    bot: Bot, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Однократно подтягивает username у пользователей, зарегистрированных до того,
    как бот начал его сохранять (username IS NULL).

    Запрашивает getChat по одному пользователю с паузой; у кого username нет, пишет
    пустую строку, поэтому при следующих запусках их уже не трогает.
    """
    async with session_factory() as session:
        users = await repo.users_missing_username(session)
        if not users:
            return
        logger.info("Заполняю username у %s пользователей", len(users))
        for user in users:
            try:
                chat = await bot.get_chat(user.tg_id)
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
                continue  # подхватим при следующем запуске или обращении к боту
            except TelegramAPIError:
                chat = None  # чат недоступен, например бот заблокирован
            user.username = (chat.username if chat else None) or ""
            await session.commit()
            await asyncio.sleep(SEND_INTERVAL)
        logger.info("Заполнение username завершено")
