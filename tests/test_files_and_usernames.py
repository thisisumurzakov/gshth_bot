"""Доставка заявок в чат, ссылки на файлы в CSV и заполнение username."""

from datetime import date

import pytest_asyncio
from aiogram import Bot, methods
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from bot.config import Settings
from bot.db import repo
from bot.db.models import ProjectApplication, User, utcnow
from bot.services.applications import notify_new_application
from bot.services.usernames import backfill_usernames

from tests.helpers import ADMIN_ID, BOT_USERNAME, FakeSession, sent_texts

APPLICATIONS_CHAT = -100555


@pytest_asyncio.fixture
async def application(session):
    user = User(
        tg_id=21, full_name="Aziza Rahimova", phone="+998901112233", language="uz",
        username="aziza", birth_date=date(2003, 4, 5), workplace="WIUT",
        subscribed_at=utcnow(),
    )
    session.add(user)
    project = await repo.create_project(
        session, title="Youth Forum", description="x", require_cv=True, require_letter=True
    )
    app = ProjectApplication(
        project_id=project.id, tg_id=21, cv_file_id="CV_21", letter_file_id="LETTER_21"
    )
    session.add(app)
    await session.commit()
    return project, app, user


def settings(**overrides) -> Settings:
    values = dict(
        bot_token="42:TEST", main_channel_id=-1001, main_channel_link="https://t.me/x",
        admin_ids=str(ADMIN_ID), applications_chat_id=APPLICATIONS_CHAT,
    )
    return Settings(**(values | overrides))


async def test_application_with_files_reaches_chat(application):
    project, app, user = application
    api = FakeSession()
    await notify_new_application(Bot("42:TEST", session=api), settings(), project, app, user)

    documents = [c.document for c in api.calls if isinstance(c, methods.SendDocument)]
    assert documents == ["CV_21", "LETTER_21"]
    assert {c.chat_id for c in api.calls} == {APPLICATIONS_CHAT}


async def test_rejected_files_fall_back_to_admins_with_reason(application):
    project, app, user = application
    api = FakeSession()
    reason = "not enough rights to send documents to the chat"
    api.fail = lambda m: (
        TelegramBadRequest(method=m, message=reason)
        if isinstance(m, methods.SendDocument) and m.chat_id == APPLICATIONS_CHAT
        else None
    )
    await notify_new_application(Bot("42:TEST", session=api), settings(), project, app, user)

    to_chat = [c for c in api.calls if c.chat_id == APPLICATIONS_CHAT]
    # Текст ушёл в чат, хотя оба документа отклонены — части не зависят друг от друга.
    assert sum(isinstance(c, methods.SendDocument) for c in to_chat) == 2
    assert any(isinstance(c, methods.SendMessage) for c in to_chat)

    to_admin = [c for c in api.calls if c.chat_id == ADMIN_ID]
    assert reason in sent_texts(to_admin) and "/check_chat" in sent_texts(to_admin)
    assert [c.document for c in to_admin if isinstance(c, methods.SendDocument)] == [
        "CV_21", "LETTER_21",
    ]


async def test_csv_links_open_files_for_admins_only(harness, application):
    project, _, _ = application
    h = harness

    calls = await h.press(ADMIN_ID, f"ap_csv:{project.id}")
    csv = next(c for c in calls if isinstance(c, methods.SendDocument))
    text = csv.document.data.decode("utf-8-sig")
    cv_link = f"https://t.me/{BOT_USERNAME}?start=cv_{project.id}_21"
    letter_link = f"https://t.me/{BOT_USERNAME}?start=letter_{project.id}_21"
    assert cv_link in text and letter_link in text and ",aziza," in text

    calls = await h.press(ADMIN_ID, "au_csv")
    users = next(c for c in calls if isinstance(c, methods.SendDocument))
    users_text = users.document.data.decode("utf-8-sig")
    assert "Youth Forum" in users_text and cv_link in users_text and letter_link in users_text

    calls = await h.send(ADMIN_ID, f"/start cv_{project.id}_21")
    document = next(c for c in calls if isinstance(c, methods.SendDocument))
    assert document.document == "CV_21" and "Aziza Rahimova" in document.caption
    calls = await h.send(ADMIN_ID, f"/start letter_{project.id}_21")
    assert next(c for c in calls if isinstance(c, methods.SendDocument)).document == "LETTER_21"
    assert "не найдена" in sent_texts(await h.send(ADMIN_ID, "/start cv_999_21"))

    # Не админ по той же ссылке файла не получает.
    calls = await h.send(21, f"/start cv_{project.id}_21")
    assert not any(isinstance(c, methods.SendDocument) for c in calls)


async def test_letter_link_shows_text_letter(harness, session_factory, application):
    project, _, _ = application
    async with session_factory() as s:
        app = await repo.get_application(s, project.id, 21)
        app.letter_file_id, app.letter_text = None, "Мечтаю участвовать"
        await s.commit()
    out = sent_texts(await harness.send(ADMIN_ID, f"/start letter_{project.id}_21"))
    assert "Мечтаю участвовать" in out


async def test_usernames_are_backfilled_once(session_factory):
    async with session_factory() as s:
        s.add_all(
            [
                User(tg_id=tg_id, full_name=f"User {tg_id}", phone=f"+99890{tg_id}", language="ru")
                for tg_id in (31, 32, 33)
            ]
        )
        await s.commit()

    api = FakeSession()
    api.chat_usernames = {31: "first_user", 32: None}
    api.fail = lambda m: (
        TelegramForbiddenError(method=m, message="bot was blocked by the user")
        if isinstance(m, methods.GetChat) and m.chat_id == 33
        else None
    )
    bot = Bot("42:TEST", session=api)
    await backfill_usernames(bot, session_factory)

    async with session_factory() as s:
        assert (await repo.get_user(s, 31)).username == "first_user"
        assert (await repo.get_user(s, 32)).username == ""  # username нет
        assert (await repo.get_user(s, 33)).username == ""  # недоступен
    # Повторный запуск Telegram уже не дёргает.
    api.calls.clear()
    await backfill_usernames(bot, session_factory)
    assert api.calls == []


async def test_check_chat_without_applications_chat(harness):
    assert "не задан" in sent_texts(await harness.send(ADMIN_ID, "/check_chat"))


async def test_check_chat_reports_missing_channel_rights(harness, monkeypatch):
    from bot.config import get_settings

    monkeypatch.setattr(get_settings(), "applications_chat_id", APPLICATIONS_CHAT)
    harness.api.chat_types[APPLICATIONS_CHAT] = "channel"
    # Бот просто подписчик канала — публиковать не может.
    harness.api.fail = lambda m: (
        TelegramBadRequest(method=m, message="need administrator rights in the channel chat")
        if isinstance(m, methods.SendMessage) and m.chat_id == APPLICATIONS_CHAT
        else None
    )
    out = sent_texts(await harness.send(ADMIN_ID, "/check_chat"))
    assert "статус бота: участник, не администратор" in out
    assert "need administrator rights" in out
    assert "администратором канала" in out
