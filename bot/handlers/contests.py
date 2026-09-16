import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import JOIN_TRANSITION, LEAVE_TRANSITION, ChatMemberUpdatedFilter
from aiogram.types import CallbackQuery, ChatMemberUpdated
from sqlalchemy.ext.asyncio import AsyncSession

from bot import keyboards
from bot.db import repo
from bot.db.models import Contest, User, utcnow
from bot.handlers.flows import ensure_menu_access
from bot.locales import t
from bot.services.cards import delete_quietly, send_card
from bot.services.contests import get_or_create_link, register_join, register_leave
from bot.services.timeutil import format_local_datetime

logger = logging.getLogger(__name__)

router = Router(name="contests")


def contest_text(lang: str | None, contest: Contest) -> str:
    return (
        f"<b>{escape(contest.title)}</b>\n\n{contest.description}\n\n"
        + t(lang, "contest_ends", date=format_local_datetime(contest.ends_at))
    )


async def show_contests(bot: Bot, session: AsyncSession, user: User) -> None:
    contests = await repo.list_running_contests(session)
    if not contests:
        await bot.send_message(user.tg_id, t(user.language, "contests_empty"))
        return
    await bot.send_message(
        user.tg_id,
        t(user.language, "contests_list"),
        reply_markup=keyboards.contests_kb(contests),
    )


async def show_contest(
    bot: Bot, session: AsyncSession, user: User, contest: Contest
) -> None:
    lang = user.language
    text = contest_text(lang, contest)
    participant = await repo.get_participant(session, contest.id, user.tg_id)
    if participant is None:
        text += "\n\n" + t(lang, "contest_how")
        link = None
    else:
        link = participant.invite_link
        count = await repo.invited_count(session, contest.id, user.tg_id)
        text += "\n\n" + t(lang, "contest_your_link", link=link, count=count)
    await send_card(
        bot,
        user.tg_id,
        text,
        contest.photo_file_id,
        keyboards.contest_kb(lang, contest.id, link),
    )


async def _running_contest(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> Contest | None:
    contest = await repo.get_contest(session, int(callback.data.split(":", 1)[1]))
    if contest is None or not contest.is_active or contest.ends_at <= utcnow():
        await callback.answer(t(user.language, "contest_unavailable"), show_alert=True)
        return None
    return contest


@router.callback_query(F.data == "cst")
async def cb_contests(
    callback: CallbackQuery, session: AsyncSession, user: User | None
) -> None:
    await callback.answer()
    if not await ensure_menu_access(callback.bot, callback.from_user.id, user):
        return
    await delete_quietly(callback.message)
    await show_contests(callback.bot, session, user)


@router.callback_query(F.data.startswith("cst:"))
async def cb_contest(
    callback: CallbackQuery, session: AsyncSession, user: User | None
) -> None:
    if not await ensure_menu_access(callback.bot, callback.from_user.id, user):
        await callback.answer()
        return
    contest = await _running_contest(callback, session, user)
    if contest is None:
        return
    await callback.answer()
    await delete_quietly(callback.message)
    await show_contest(callback.bot, session, user, contest)


@router.callback_query(F.data.startswith("cst_link:"))
async def cb_contest_link(
    callback: CallbackQuery, session: AsyncSession, user: User | None
) -> None:
    if not await ensure_menu_access(callback.bot, callback.from_user.id, user):
        await callback.answer()
        return
    contest = await _running_contest(callback, session, user)
    if contest is None:
        return
    try:
        await get_or_create_link(callback.bot, session, contest, user.tg_id)
    except TelegramAPIError:
        # Например, бота лишили прав администратора в канале конкурса.
        logger.exception("Не удалось создать ссылку для конкурса %s", contest.id)
        await callback.answer(t(user.language, "contest_link_error"), show_alert=True)
        return
    await callback.answer()
    await delete_quietly(callback.message)
    await show_contest(callback.bot, session, user, contest)


# --- Подсчёт приглашённых. Обновления chat_member приходят из всех чатов, где бот
# админ; вступления без пригласительной ссылки отсекаются без обращения к базе. ---


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def on_join(event: ChatMemberUpdated, session: AsyncSession) -> None:
    if event.invite_link is None:
        return
    await register_join(
        session,
        channel_id=event.chat.id,
        invite_link=event.invite_link.invite_link,
        joined_tg_id=event.new_chat_member.user.id,
        joined_at=event.date,
    )


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=LEAVE_TRANSITION))
async def on_leave(event: ChatMemberUpdated, session: AsyncSession) -> None:
    await register_leave(
        session,
        channel_id=event.chat.id,
        left_tg_id=event.new_chat_member.user.id,
        left_at=event.date,
    )
