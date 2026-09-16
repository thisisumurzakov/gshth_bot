import asyncio
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repo
from bot.db.models import Contest, ContestJoin, ContestParticipant
from bot.services.broadcast import SEND_INTERVAL

logger = logging.getLogger(__name__)


async def get_or_create_link(
    bot: Bot, session: AsyncSession, contest: Contest, tg_id: int
) -> str:
    """Персональная ссылка участника в канал конкурса.

    Ссылка истекает вместе с конкурсом, так что отзывать её потом не нужно.
    """
    participant = await repo.get_participant(session, contest.id, tg_id)
    if participant is not None:
        return participant.invite_link

    link = await bot.create_chat_invite_link(
        contest.channel_id,
        name=f"contest {contest.id} {tg_id}",
        expire_date=contest.ends_at,
    )
    session.add(
        ContestParticipant(
            contest_id=contest.id, tg_id=tg_id, invite_link=link.invite_link
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        # Двойное нажатие: ссылку уже успел сохранить параллельный апдейт.
        await session.rollback()
        participant = await repo.get_participant(session, contest.id, tg_id)
        return participant.invite_link
    return link.invite_link


async def register_join(
    session: AsyncSession,
    channel_id: int,
    invite_link: str,
    joined_tg_id: int,
    joined_at: datetime,
) -> bool:
    """Засчитывает вступление в канал конкурса по персональной ссылке.

    Не засчитывается: чужая ссылка, другой канал, конкурс завершён или скрыт,
    самоприглашение, человек уже засчитан в этом конкурсе (в том числе другому
    участнику). Вышедший и вернувшийся по той же ссылке засчитывается снова.
    """
    participant = await repo.get_participant_by_link(session, invite_link)
    if participant is None or participant.tg_id == joined_tg_id:
        return False
    contest = await repo.get_contest(session, participant.contest_id)
    if (
        contest is None
        or contest.channel_id != channel_id
        or not contest.is_active
        or joined_at >= contest.ends_at
    ):
        return False

    existing = await session.get(ContestJoin, (contest.id, joined_tg_id))
    if existing is not None:
        if existing.left_at is None or existing.inviter_tg_id != participant.tg_id:
            return False
        existing.left_at = None
        await session.commit()
        return True

    session.add(
        ContestJoin(
            contest_id=contest.id,
            joined_tg_id=joined_tg_id,
            inviter_tg_id=participant.tg_id,
            joined_at=joined_at,
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return False
    return True


async def register_leave(
    session: AsyncSession, channel_id: int, left_tg_id: int, left_at: datetime
) -> None:
    """Вышедший из канала до окончания конкурса перестаёт засчитываться."""
    result = await session.execute(
        select(ContestJoin)
        .join(Contest, Contest.id == ContestJoin.contest_id)
        .where(
            ContestJoin.joined_tg_id == left_tg_id,
            ContestJoin.left_at.is_(None),
            Contest.channel_id == channel_id,
            Contest.ends_at > left_at,
        )
    )
    joins = list(result.scalars())
    if not joins:
        return
    for join in joins:
        join.left_at = left_at
    await session.commit()


async def reschedule_links(
    bot: Bot, session: AsyncSession, contest: Contest
) -> tuple[int, int]:
    """После переноса даты окончания продлевает (или сокращает) уже выданные ссылки.

    Срок жизни ссылки задаётся при создании, поэтому без этого участники со
    старыми ссылками потеряли бы к ним доступ. Возвращает (обновлено, ошибок).
    """
    updated = failed = 0
    for participant in await repo.list_participants(session, contest.id):
        try:
            await bot.edit_chat_invite_link(
                contest.channel_id,
                participant.invite_link,
                expire_date=contest.ends_at,
            )
            updated += 1
        except TelegramAPIError:
            logger.exception("Не удалось продлить ссылку %s", participant.invite_link)
            failed += 1
        await asyncio.sleep(SEND_INTERVAL)
    return updated, failed
