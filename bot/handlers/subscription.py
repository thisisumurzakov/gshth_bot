from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.models import User
from bot.locales import t
from bot.services.invites import create_personal_link

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

    settings = get_settings()
    lang = user.language
    try:
        member = await callback.bot.get_chat_member(
            settings.main_channel_id, user.tg_id
        )
        subscribed = member.status in SUBSCRIBED
    except TelegramBadRequest:
        # Telegram может не знать пользователя в контексте канала — значит, не подписан.
        subscribed = False
    if not subscribed:
        await callback.answer(t(lang, "not_subscribed"), show_alert=True)
        return

    await callback.answer()
    if user.invite_link is None:
        user.invite_link = await create_personal_link(
            callback.bot, settings.main_channel_id, user.tg_id
        )
        await session.commit()
    await callback.message.answer(
        t(lang, "invite_ready", link=user.invite_link, goal=settings.referral_goal)
    )
