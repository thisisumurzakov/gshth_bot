import pytest
import pytest_asyncio

from bot.db import repo
from bot.db.base import Base, make_session_factory
from bot.db.models import User
from bot.services.referrals import register_join
from sqlalchemy.ext.asyncio import create_async_engine

LINK = "https://t.me/+abc123"


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = make_session_factory(engine)
    async with factory() as session:
        session.add(
            User(
                tg_id=1,
                full_name="Test Inviter",
                phone="+998901112233",
                language="ru",
                invite_link=LINK,
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_join_is_counted(session):
    result = await register_join(session, LINK, joined_tg_id=100)
    assert result is not None
    inviter, count = result
    assert inviter.tg_id == 1
    assert count == 1


@pytest.mark.asyncio
async def test_unknown_link_is_ignored(session):
    assert await register_join(session, "https://t.me/+other", 100) is None


@pytest.mark.asyncio
async def test_self_invite_is_ignored(session):
    assert await register_join(session, LINK, joined_tg_id=1) is None
    assert await repo.referral_count(session, 1) == 0


@pytest.mark.asyncio
async def test_rejoin_is_counted_once(session):
    assert await register_join(session, LINK, 100) is not None
    assert await register_join(session, LINK, 100) is None
    assert await repo.referral_count(session, 1) == 1


@pytest.mark.asyncio
async def test_goal_of_three(session):
    for joined_id in (100, 200, 300):
        result = await register_join(session, LINK, joined_id)
        assert result is not None
    _, count = result
    assert count == 3


@pytest.mark.asyncio
async def test_same_person_counts_for_one_inviter_only(session):
    other_link = "https://t.me/+second"
    session.add(
        User(
            tg_id=2,
            full_name="Second Inviter",
            phone="+998907654321",
            language="en",
            invite_link=other_link,
        )
    )
    await session.commit()
    assert await register_join(session, LINK, 100) is not None
    assert await register_join(session, other_link, 100) is None
    assert await repo.referral_count(session, 1) == 1
    assert await repo.referral_count(session, 2) == 0
