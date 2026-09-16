from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from bot.db import repo
from bot.db.base import create_schema, make_session_factory
from bot.services.timeutil import (
    format_local_datetime,
    parse_birth_date,
    parse_local_datetime,
)


async def test_legacy_database_is_upgraded(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'old.db'}")
    async with engine.begin() as conn:
        # Схема users из первой версии бота.
        await conn.execute(
            text(
                "CREATE TABLE users (tg_id BIGINT PRIMARY KEY, full_name VARCHAR(255), "
                "phone VARCHAR(32), language VARCHAR(5), invite_link VARCHAR(255), "
                "private_invite_link VARCHAR(255), created_at DATETIME)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO users VALUES "
                "(1, 'Old Subscribed', '+998901', 'ru', 'https://t.me/+x', NULL, "
                "'2026-09-02 10:00:00.000000'), "
                "(2, 'Old Unsubscribed', '+998902', 'uz', NULL, NULL, "
                "'2026-09-02 11:00:00.000000')"
            )
        )

    await create_schema(engine)
    await create_schema(engine)  # повторный запуск ничего не ломает

    async with make_session_factory(engine)() as session:
        subscribed = await repo.get_user(session, 1)
        assert subscribed.subscribed_at == datetime(2026, 9, 2, 10, tzinfo=timezone.utc)
        assert not subscribed.profile_complete
        assert (await repo.get_user(session, 2)).subscribed_at is None
        assert len(await repo.users_with_incomplete_profile(session)) == 2

        await repo.update_profile(session, subscribed, date(2001, 5, 6), "TUIT")
        assert await repo.stats(session) == (2, 1, 1)
    await engine.dispose()


def test_parse_birth_date():
    today = date(2026, 9, 16)
    assert parse_birth_date("15.03.2002", today) == date(2002, 3, 15)
    assert parse_birth_date(" 15/03/2002 ", today) == date(2002, 3, 15)
    assert parse_birth_date("31.02.2002", today) is None
    assert parse_birth_date("2002-03-15", today) is None
    assert parse_birth_date("01.01.2020", today) is None  # младше 10 лет
    assert parse_birth_date("01.01.1900", today) is None


def test_local_datetime_is_tashkent_time():
    value = parse_local_datetime("30.09.2026 18:00")
    assert value == datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc)
    assert format_local_datetime(value) == "30.09.2026 18:00"
    assert parse_local_datetime("30.09.2026") is None
