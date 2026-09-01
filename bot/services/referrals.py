from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repo
from bot.db.models import Referral, User


async def register_join(
    session: AsyncSession, invite_link: str, joined_tg_id: int
) -> tuple[User, int] | None:
    """Засчитывает вступление в канал по персональной ссылке.

    Возвращает (пригласивший, его текущий счётчик) или None, если засчитывать
    нечего: ссылка не наша, самоприглашение или этот человек уже был засчитан.
    """
    inviter = await repo.get_user_by_invite_link(session, invite_link)
    if inviter is None or inviter.tg_id == joined_tg_id:
        return None

    session.add(Referral(inviter_tg_id=inviter.tg_id, joined_tg_id=joined_tg_id))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return None

    count = await repo.referral_count(session, inviter.tg_id)
    return inviter, count
