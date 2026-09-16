from datetime import date, timedelta

import pytest_asyncio

from bot.db import repo
from bot.db.models import Contest, ContestParticipant, User, utcnow
from bot.services.contests import register_join, register_leave

CHANNEL = -100500
LINK_A = "https://t.me/+aaa"
LINK_B = "https://t.me/+bbb"


@pytest_asyncio.fixture
async def contest(session):
    for tg_id, name in ((1, "Inviter A"), (2, "Inviter B")):
        session.add(
            User(
                tg_id=tg_id,
                full_name=name,
                phone=f"+99890000000{tg_id}",
                language="ru",
                birth_date=date(2000, 1, 1),
                workplace="NUUz",
            )
        )
    contest = Contest(
        title="Contest",
        description="desc",
        channel_id=CHANNEL,
        channel_title="Channel",
        ends_at=utcnow() + timedelta(days=7),
    )
    session.add(contest)
    await session.flush()
    session.add_all(
        [
            ContestParticipant(contest_id=contest.id, tg_id=1, invite_link=LINK_A),
            ContestParticipant(contest_id=contest.id, tg_id=2, invite_link=LINK_B),
        ]
    )
    await session.commit()
    return contest


async def join(session, link, tg_id, channel=CHANNEL, at=None):
    return await register_join(session, channel, link, tg_id, at or utcnow())


async def test_join_is_counted(session, contest):
    assert await join(session, LINK_A, 100)
    assert await repo.invited_count(session, contest.id, 1) == 1


async def test_unknown_link_and_self_invite_are_ignored(session, contest):
    assert not await join(session, "https://t.me/+other", 100)
    assert not await join(session, LINK_A, 1)
    assert await repo.invited_count(session, contest.id, 1) == 0


async def test_join_to_other_channel_is_ignored(session, contest):
    assert not await join(session, LINK_A, 100, channel=-1)


async def test_join_after_end_is_ignored(session, contest):
    assert not await join(session, LINK_A, 100, at=contest.ends_at + timedelta(seconds=1))


async def test_hidden_contest_does_not_count(session, contest):
    contest.is_active = False
    await session.commit()
    assert not await join(session, LINK_A, 100)


async def test_person_counts_once_and_for_one_inviter(session, contest):
    assert await join(session, LINK_A, 100)
    assert not await join(session, LINK_A, 100)
    assert not await join(session, LINK_B, 100)
    assert await repo.invited_count(session, contest.id, 1) == 1
    assert await repo.invited_count(session, contest.id, 2) == 0


async def test_leave_before_end_uncounts_and_rejoin_counts_again(session, contest):
    assert await join(session, LINK_A, 100)
    await register_leave(session, CHANNEL, 100, utcnow())
    assert await repo.invited_count(session, contest.id, 1) == 0
    # Вернуться по чужой ссылке, чтобы «перекинуть» голос, нельзя.
    assert not await join(session, LINK_B, 100)
    assert await join(session, LINK_A, 100)
    assert await repo.invited_count(session, contest.id, 1) == 1


async def test_leave_after_end_keeps_count(session, contest):
    assert await join(session, LINK_A, 100)
    await register_leave(session, CHANNEL, 100, contest.ends_at + timedelta(hours=1))
    assert await repo.invited_count(session, contest.id, 1) == 1


async def test_ranking_orders_by_count_and_includes_zero(session, contest):
    for tg_id in (100, 101):
        assert await join(session, LINK_B, tg_id)
    assert await join(session, LINK_A, 102)
    ranking = await repo.contest_ranking(session, contest.id)
    assert [(user.tg_id, count) for user, count in ranking] == [(2, 2), (1, 1)]
    assert await repo.contest_totals(session, contest.id) == (2, 3)


async def test_running_contests_excludes_finished(session, contest):
    assert [c.id for c in await repo.list_running_contests(session)] == [contest.id]
    assert await repo.list_running_contests(session, now=contest.ends_at) == []
