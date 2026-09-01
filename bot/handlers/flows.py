"""Общие шаги сценария, используемые из нескольких обработчиков."""

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from bot import keyboards
from bot.config import Settings
from bot.db import repo
from bot.db.models import User
from bot.locales import t


async def send_subscribe_prompt(
    bot: Bot, chat_id: int, lang: str, settings: Settings
) -> None:
    await bot.send_message(
        chat_id,
        t(lang, "subscribe_prompt"),
        reply_markup=keyboards.subscribe_kb(lang, settings.main_channel_link),
    )


async def send_menu(
    bot: Bot, session: AsyncSession, user: User, settings: Settings
) -> None:
    lang = user.language
    if user.private_invite_link:
        status = t(lang, "menu_done", link=user.private_invite_link)
    else:
        count = await repo.referral_count(session, user.tg_id)
        status = t(
            lang,
            "menu_progress",
            link=user.invite_link,
            count=count,
            goal=settings.referral_goal,
        )
    text = t(lang, "menu_header", name=user.full_name) + "\n\n" + status
    await bot.send_message(user.tg_id, text, reply_markup=keyboards.menu_kb(lang))
