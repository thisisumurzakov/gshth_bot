import asyncio
import logging

from aiogram import Bot, Dispatcher

from bot.config import get_settings
from bot.db.base import create_schema, make_engine, make_session_factory
from bot.handlers import admin, referral, registration, start, subscription
from bot.middlewares.db import DbSessionMiddleware, UserMiddleware


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()

    engine = make_engine(settings.db_path)
    await create_schema(engine)
    session_factory = make_session_factory(engine)

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    dp.update.outer_middleware(DbSessionMiddleware(session_factory))
    dp.message.middleware(UserMiddleware())
    dp.callback_query.middleware(UserMiddleware())

    dp.include_routers(
        admin.router,
        start.router,
        registration.router,
        subscription.router,
        referral.router,
    )

    # chat_member обязателен: без него Telegram не присылает события вступления в канал.
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(
        bot, allowed_updates=["message", "callback_query", "chat_member"]
    )


if __name__ == "__main__":
    asyncio.run(main())
