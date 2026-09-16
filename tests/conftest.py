import os

# Роутеры читают настройки при импорте — задаём их до импорта модулей бота.
os.environ.setdefault("BOT_TOKEN", "42:TEST")
os.environ.setdefault("MAIN_CHANNEL_ID", "-1001")
os.environ.setdefault("MAIN_CHANNEL_LINK", "https://t.me/test")
os.environ.setdefault("ADMIN_IDS", "999")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from bot.db.base import create_schema, make_session_factory  # noqa: E402

from tests.helpers import Harness  # noqa: E402


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite://")
    await create_schema(engine)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return make_session_factory(engine)


@pytest_asyncio.fixture
async def session(session_factory):
    async with session_factory() as session:
        yield session


@pytest.fixture
def harness(session_factory):
    h = Harness(session_factory)
    yield h
    # Роутеры — модульные синглтоны; отцепляем, чтобы следующий тест собрал свой Dispatcher.
    for router in h.dp.sub_routers:
        router._parent_router = None
