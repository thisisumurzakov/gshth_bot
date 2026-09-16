from datetime import date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import (
    Contest,
    ContestJoin,
    ContestParticipant,
    Project,
    ProjectApplication,
    User,
    utcnow,
)


# --- Пользователи ---


async def get_user(session: AsyncSession, tg_id: int) -> User | None:
    return await session.get(User, tg_id)


async def get_user_by_phone(session: AsyncSession, phone: str) -> User | None:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not digits:
        return None  # иначе пустая строка «совпала» бы с любым номером
    result = await session.execute(select(User))
    for user in result.scalars():
        if "".join(ch for ch in user.phone if ch.isdigit()).endswith(digits):
            return user
    return None


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    result = await session.execute(
        select(User).where(func.lower(User.username) == username.lstrip("@").lower())
    )
    return result.scalars().first()


async def create_user(
    session: AsyncSession,
    tg_id: int,
    full_name: str,
    phone: str,
    language: str,
    username: str | None = None,
) -> User:
    user = User(
        tg_id=tg_id, full_name=full_name, phone=phone, language=language, username=username
    )
    session.add(user)
    await session.commit()
    return user


async def update_profile(
    session: AsyncSession, user: User, birth_date: date, workplace: str
) -> None:
    user.birth_date = birth_date
    user.workplace = workplace
    await session.commit()


async def all_user_ids(session: AsyncSession) -> list[int]:
    result = await session.execute(select(User.tg_id))
    return list(result.scalars())


async def users_with_incomplete_profile(session: AsyncSession) -> list[User]:
    result = await session.execute(
        select(User).where(or_(User.birth_date.is_(None), User.workplace.is_(None)))
    )
    return list(result.scalars())


def _user_search(query: str | None):
    """Поиск по части имени, username или по цифрам телефона."""
    if not query:
        return []
    digits = "".join(ch for ch in query if ch.isdigit())
    text = query.strip().lstrip("@")
    conditions = [User.full_name.ilike(f"%{text}%"), User.username.ilike(f"%{text}%")]
    if digits:
        conditions.append(User.phone.like(f"%{digits}%"))
    return [or_(*conditions)]


async def count_users(session: AsyncSession, query: str | None = None) -> int:
    result = await session.execute(
        select(func.count()).select_from(User).where(*_user_search(query))
    )
    return int(result.scalar_one())


async def list_users(
    session: AsyncSession, query: str | None = None, offset: int = 0, limit: int = 10
) -> list[User]:
    result = await session.execute(
        select(User)
        .where(*_user_search(query))
        .order_by(User.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars())


async def all_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User).order_by(User.created_at))
    return list(result.scalars())


async def user_applications(
    session: AsyncSession, tg_id: int
) -> list[tuple[ProjectApplication, Project]]:
    result = await session.execute(
        select(ProjectApplication, Project)
        .join(Project, Project.id == ProjectApplication.project_id)
        .where(ProjectApplication.tg_id == tg_id)
        .order_by(ProjectApplication.created_at)
    )
    return [(app, project) for app, project in result.all()]


async def stats(session: AsyncSession) -> tuple[int, int, int]:
    """(всего, подтвердили подписку, заполнили профиль)."""

    async def count(*where) -> int:
        query = select(func.count()).select_from(User)
        if where:
            query = query.where(*where)
        return int((await session.execute(query)).scalar_one())

    return (
        await count(),
        await count(User.subscribed_at.is_not(None)),
        await count(User.birth_date.is_not(None), User.workplace.is_not(None)),
    )


# --- Проекты ---


async def create_project(session: AsyncSession, **fields) -> Project:
    project = Project(**fields)
    session.add(project)
    await session.commit()
    return project


async def list_projects(session: AsyncSession, only_active: bool) -> list[Project]:
    query = select(Project).order_by(Project.id.desc())
    if only_active:
        query = query.where(Project.is_active.is_(True))
    return list((await session.execute(query)).scalars())


async def get_project(session: AsyncSession, project_id: int) -> Project | None:
    return await session.get(Project, project_id)


async def get_application(
    session: AsyncSession, project_id: int, tg_id: int
) -> ProjectApplication | None:
    return await session.get(ProjectApplication, (project_id, tg_id))


async def application_count(session: AsyncSession, project_id: int) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(ProjectApplication)
        .where(ProjectApplication.project_id == project_id)
    )
    return int(result.scalar_one())


async def project_applications(
    session: AsyncSession, project_id: int
) -> list[tuple[ProjectApplication, User]]:
    result = await session.execute(
        select(ProjectApplication, User)
        .join(User, User.tg_id == ProjectApplication.tg_id)
        .where(ProjectApplication.project_id == project_id)
        .order_by(ProjectApplication.created_at)
    )
    return [(app, user) for app, user in result.all()]


# --- Конкурсы ---


async def create_contest(session: AsyncSession, **fields) -> Contest:
    contest = Contest(**fields)
    session.add(contest)
    await session.commit()
    return contest


async def list_contests(session: AsyncSession) -> list[Contest]:
    result = await session.execute(select(Contest).order_by(Contest.id.desc()))
    return list(result.scalars())


async def list_running_contests(
    session: AsyncSession, now: datetime | None = None
) -> list[Contest]:
    result = await session.execute(
        select(Contest)
        .where(Contest.is_active.is_(True), Contest.ends_at > (now or utcnow()))
        .order_by(Contest.ends_at)
    )
    return list(result.scalars())


async def get_contest(session: AsyncSession, contest_id: int) -> Contest | None:
    return await session.get(Contest, contest_id)


async def get_participant(
    session: AsyncSession, contest_id: int, tg_id: int
) -> ContestParticipant | None:
    return await session.get(ContestParticipant, (contest_id, tg_id))


async def list_participants(
    session: AsyncSession, contest_id: int
) -> list[ContestParticipant]:
    result = await session.execute(
        select(ContestParticipant).where(ContestParticipant.contest_id == contest_id)
    )
    return list(result.scalars())


async def get_participant_by_link(
    session: AsyncSession, link: str
) -> ContestParticipant | None:
    result = await session.execute(
        select(ContestParticipant).where(ContestParticipant.invite_link == link)
    )
    return result.scalar_one_or_none()


def _counted_joins(contest_id: int):
    return (ContestJoin.contest_id == contest_id, ContestJoin.left_at.is_(None))


async def invited_count(session: AsyncSession, contest_id: int, tg_id: int) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(ContestJoin)
        .where(*_counted_joins(contest_id), ContestJoin.inviter_tg_id == tg_id)
    )
    return int(result.scalar_one())


async def contest_totals(session: AsyncSession, contest_id: int) -> tuple[int, int]:
    """(участников со ссылкой, засчитанных приглашённых)."""
    participants = await session.execute(
        select(func.count())
        .select_from(ContestParticipant)
        .where(ContestParticipant.contest_id == contest_id)
    )
    joins = await session.execute(
        select(func.count()).select_from(ContestJoin).where(*_counted_joins(contest_id))
    )
    return int(participants.scalar_one()), int(joins.scalar_one())


async def user_contests(session: AsyncSession, tg_id: int) -> list[tuple[Contest, int]]:
    invited = (
        select(func.count())
        .select_from(ContestJoin)
        .where(
            ContestJoin.contest_id == Contest.id,
            ContestJoin.left_at.is_(None),
            ContestJoin.inviter_tg_id == tg_id,
        )
        .scalar_subquery()
    )
    result = await session.execute(
        select(Contest, invited)
        .join(ContestParticipant, ContestParticipant.contest_id == Contest.id)
        .where(ContestParticipant.tg_id == tg_id)
        .order_by(Contest.ends_at.desc())
    )
    return [(contest, int(count)) for contest, count in result.all()]


async def contest_ranking(
    session: AsyncSession, contest_id: int, limit: int | None = None, offset: int = 0
) -> list[tuple[User, int]]:
    """Участники конкурса по убыванию числа засчитанных приглашённых (для админов)."""
    invited = (
        select(ContestJoin.inviter_tg_id, func.count().label("cnt"))
        .where(*_counted_joins(contest_id))
        .group_by(ContestJoin.inviter_tg_id)
        .subquery()
    )
    cnt = func.coalesce(invited.c.cnt, 0)
    query = (
        select(User, cnt)
        .join(ContestParticipant, ContestParticipant.tg_id == User.tg_id)
        .outerjoin(invited, invited.c.inviter_tg_id == User.tg_id)
        .where(ContestParticipant.contest_id == contest_id)
        .order_by(cnt.desc(), ContestParticipant.created_at)
    )
    if limit is not None:
        query = query.limit(limit).offset(offset)
    return [(user, int(count)) for user, count in (await session.execute(query)).all()]
