import asyncio
import logging

from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import get_settings
from bot.db.base import create_schema, make_engine, make_session_factory
from bot.handlers import (
    admin,
    admin_contests,
    admin_projects,
    admin_users,
    contests,
    menu,
    projects,
    registration,
    start,
    subscription,
)
from bot.middlewares.db import DbSessionMiddleware, UserMiddleware
from bot.services.usernames import backfill_usernames


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()

    engine = make_engine(settings.db_path)
    await create_schema(engine)
    session_factory = make_session_factory(engine)
    dp = build_dispatcher(session_factory)
    bot = Bot(token=settings.bot_token)

    # В фоне, чтобы не задерживать старт: getChat идёт по одному пользователю с паузой.
    backfill = asyncio.create_task(backfill_usernames(bot, session_factory))

    # chat_member обязателен: без него Telegram не присылает события вступления
    # в каналы конкурсов.
    await bot.delete_webhook(drop_pending_updates=False)
    try:
        await dp.start_polling(
            bot, allowed_updates=["message", "callback_query", "chat_member"]
        )
    finally:
        backfill.cancel()


def build_dispatcher(session_factory: async_sessionmaker[AsyncSession]) -> Dispatcher:
    dp = Dispatcher()
    dp.update.outer_middleware(DbSessionMiddleware(session_factory))
    # outer: пользователь нужен уже фильтрам (анкета для недозаполненных профилей),
    # а внутренние middleware выполняются только после фильтров.
    dp.message.outer_middleware(UserMiddleware())
    dp.callback_query.outer_middleware(UserMiddleware())

    # Порядок важен: админка → анкета (перехватывает недозаполненные профили) →
    # /start → кнопки меню (выходят из любого сценария) → остальные сценарии.
    dp.include_routers(
        admin.router,
        admin_projects.router,
        admin_contests.router,
        admin_users.router,
        registration.router,
        start.router,
        menu.router,
        subscription.router,
        projects.router,
        contests.router,
    )
    return dp


if __name__ == "__main__":
    asyncio.run(main())
