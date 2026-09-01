import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import JOIN_TRANSITION, ChatMemberUpdatedFilter
from aiogram.types import ChatMemberUpdated
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.locales import t
from bot.services.invites import create_private_link
from bot.services.referrals import register_join

logger = logging.getLogger(__name__)

router = Router(name="referral")


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def on_channel_join(event: ChatMemberUpdated, session: AsyncSession) -> None:
    settings = get_settings()
    if event.chat.id != settings.main_channel_id or event.invite_link is None:
        return

    result = await register_join(
        session, event.invite_link.invite_link, event.new_chat_member.user.id
    )
    if result is None:
        return
    inviter, count = result
    if inviter.private_invite_link is not None:
        return  # цель уже достигнута, ничего не сообщаем

    lang = inviter.language
    try:
        if count >= settings.referral_goal:
            inviter.private_invite_link = await create_private_link(
                event.bot, settings.private_channel_id, inviter.tg_id
            )
            await session.commit()
            await event.bot.send_message(
                inviter.tg_id,
                t(
                    lang,
                    "goal_reached",
                    goal=settings.referral_goal,
                    link=inviter.private_invite_link,
                ),
            )
        else:
            await event.bot.send_message(
                inviter.tg_id,
                t(lang, "referral_progress", count=count, goal=settings.referral_goal),
            )
    except TelegramAPIError:
        # Пользователь мог заблокировать бота — подсчёт при этом не страдает.
        logger.warning("Не удалось уведомить пользователя %s", inviter.tg_id)
