from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Referral, User


async def get_user(session: AsyncSession, tg_id: int) -> User | None:
    return await session.get(User, tg_id)


async def get_user_by_phone(session: AsyncSession, phone: str) -> User | None:
    digits = "".join(ch for ch in phone if ch.isdigit())
    result = await session.execute(select(User))
    for user in result.scalars():
        if "".join(ch for ch in user.phone if ch.isdigit()).endswith(digits):
            return user
    return None


async def get_user_by_invite_link(session: AsyncSession, link: str) -> User | None:
    result = await session.execute(select(User).where(User.invite_link == link))
    return result.scalar_one_or_none()


async def create_user(
    session: AsyncSession, tg_id: int, full_name: str, phone: str, language: str
) -> User:
    user = User(tg_id=tg_id, full_name=full_name, phone=phone, language=language)
    session.add(user)
    await session.commit()
    return user


async def all_user_ids(session: AsyncSession) -> list[int]:
    result = await session.execute(select(User.tg_id))
    return list(result.scalars())


async def referral_count(session: AsyncSession, inviter_tg_id: int) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Referral)
        .where(Referral.inviter_tg_id == inviter_tg_id)
    )
    return int(result.scalar_one())


async def stats(session: AsyncSession) -> tuple[int, int]:
    total = int(
        (await session.execute(select(func.count()).select_from(User))).scalar_one()
    )
    completed = int(
        (
            await session.execute(
                select(func.count())
                .select_from(User)
                .where(User.private_invite_link.is_not(None))
            )
        ).scalar_one()
    )
    return total, completed
