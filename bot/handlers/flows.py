"""Общие шаги сценария, используемые из нескольких обработчиков."""

from aiogram import Bot

from bot import keyboards
from bot.config import get_settings
from bot.db.models import User
from bot.locales import t

CHOOSE_LANGUAGE_PROMPT = "Tilni tanlang / Выберите язык / Choose a language:"


async def send_language_prompt(bot: Bot, chat_id: int) -> None:
    await bot.send_message(chat_id, CHOOSE_LANGUAGE_PROMPT, reply_markup=keyboards.language_kb())


async def send_subscribe_prompt(bot: Bot, chat_id: int, lang: str) -> None:
    await bot.send_message(
        chat_id,
        t(lang, "subscribe_prompt"),
        reply_markup=keyboards.subscribe_kb(lang, get_settings().main_channel_link),
    )


async def send_menu(bot: Bot, user: User, prefix: str | None = None) -> None:
    text = t(user.language, "menu_header", name=user.full_name)
    if prefix:
        text = f"{prefix}\n\n{text}"
    await bot.send_message(
        user.tg_id, text, reply_markup=keyboards.main_menu_kb(user.language)
    )


async def send_next_step(bot: Bot, user: User, prefix: str | None = None) -> None:
    """Куда вести пользователя с заполненным профилем: подписка или главное меню."""
    if user.subscribed_at is None:
        if prefix:
            await bot.send_message(user.tg_id, prefix)
        await send_subscribe_prompt(bot, user.tg_id, user.language)
    else:
        await send_menu(bot, user, prefix)


async def ensure_menu_access(bot: Bot, chat_id: int, user: User | None) -> bool:
    """Разделы меню доступны только после регистрации и подтверждения подписки."""
    if user is None:
        await send_language_prompt(bot, chat_id)
        return False
    if user.subscribed_at is None:
        await send_subscribe_prompt(bot, chat_id, user.language)
        return False
    return True
