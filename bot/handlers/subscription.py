from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.models import User, utcnow
from bot.handlers.flows import send_menu
from bot.locales import t

router = Router(name="subscription")

SUBSCRIBED = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.CREATOR,
}


@router.callback_query(F.data == "check_sub")
async def cb_check_subscription(
    callback: CallbackQuery, session: AsyncSession, user: User | None
) -> None:
    if user is None:
        # Кнопка нажата до завершения регистрации (например, после сброса БД).
        await callback.answer()
        return

    lang = user.language
    try:
        member = await callback.bot.get_chat_member(
            get_settings().main_channel_id, user.tg_id
        )
        subscribed = member.status in SUBSCRIBED
    except TelegramBadRequest:
        # Telegram может не знать пользователя в контексте канала — значит, не подписан.
        subscribed = False
    if not subscribed:
        await callback.answer(t(lang, "not_subscribed"), show_alert=True)
        return

    await callback.answer()
    prefix = None
    if user.subscribed_at is None:
        user.subscribed_at = utcnow()
        await session.commit()
        prefix = t(lang, "subscribed_ok")
    await send_menu(callback.bot, user, prefix)
