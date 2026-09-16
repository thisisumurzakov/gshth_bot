"""Админка: просмотр пользователей и их файлов, редактирование проектов и конкурсов."""

from datetime import date, timedelta

import pytest_asyncio
from aiogram import methods
from aiogram.types import PhotoSize

from bot.db import repo
from bot.db.models import ContestParticipant, ProjectApplication, User, utcnow
from bot.services.timeutil import TASHKENT

from tests.helpers import ADMIN_ID, CHANNEL_ID, sent_texts


def buttons(markup) -> list[tuple[str, str]]:
    return [
        (button.text, button.callback_data)
        for row in markup.inline_keyboard
        for button in row
    ]


@pytest_asyncio.fixture
async def data(session):
    session.add_all(
        [
            User(
                tg_id=tg_id, full_name=name, phone=phone, language="ru",
                birth_date=date(2001, 2, 3), workplace="TUIT", subscribed_at=utcnow(),
            )
            for tg_id, name, phone in (
                (11, "Anvar Karimov", "+998901234567"),
                (12, "Dilnoza Yusupova", "+998907654321"),
            )
        ]
    )
    project = await repo.create_project(
        session, title="Hub Project", description="About", require_cv=True
    )
    contest = await repo.create_contest(
        session, title="Invite Race", description="Prize",
        channel_id=CHANNEL_ID, channel_title="Channel",
        ends_at=utcnow() + timedelta(days=5),
    )
    session.add_all(
        [
            ProjectApplication(
                project_id=project.id, tg_id=11,
                cv_file_id="CV_11", letter_text="Хочу участвовать в проекте",
            ),
            ContestParticipant(
                contest_id=contest.id, tg_id=11, invite_link="https://t.me/+one"
            ),
        ]
    )
    await session.commit()
    return project, contest


async def test_admin_browses_users_and_files(harness, data):
    project, _ = data
    h = harness

    calls = await h.send(ADMIN_ID, "/users")
    assert "Зарегистрировано: 2" in calls[-1].text
    names = [text for text, _ in buttons(calls[-1].reply_markup)]
    assert any("Anvar Karimov — +998901234567" in name for name in names)

    # Поиск по имени и по цифрам телефона.
    calls = await h.send(ADMIN_ID, "/users Dilnoza")
    assert "Найдено по «Dilnoza»: 1" in calls[-1].text
    calls = await h.send(ADMIN_ID, "/users 901234567")
    assert "Найдено" in calls[-1].text
    assert [data for _, data in buttons(calls[-1].reply_markup)][0] == "au:11:u"

    # Карточка человека: профиль, заявки, конкурсы.
    calls = await h.press(ADMIN_ID, "au:11:u")
    card = next(c for c in calls if isinstance(c, methods.EditMessageText))
    assert "Anvar Karimov" in card.text and "+998901234567" in card.text
    assert "03.02.2001" in card.text and "TUIT" in card.text
    assert "Hub Project" in card.text and "CV" in card.text
    assert "Invite Race — приглашено 0" in card.text
    assert ("⬅️ К списку", "au_page:0:") in buttons(card.reply_markup)

    # Файлы приходят по file_id, письмо — текстом.
    calls = await h.press(ADMIN_ID, "au_files:11")
    document = next(c for c in calls if isinstance(c, methods.SendDocument))
    assert document.document == "CV_11" and "Hub Project" in document.caption
    assert "Хочу участвовать" in sent_texts(await h.press(ADMIN_ID, "au_letters:11"))

    # Выгрузка всех пользователей.
    calls = await h.press(ADMIN_ID, "au_csv")
    csv = next(c for c in calls if isinstance(c, methods.SendDocument))
    assert "Anvar Karimov" in csv.document.data.decode("utf-8-sig")

    # Из карточки проекта — список заявок, оттуда карточка человека с возвратом к проекту.
    calls = await h.press(ADMIN_ID, f"ap_apps:{project.id}:0")
    listing = next(c for c in calls if isinstance(c, methods.EditMessageText))
    assert ("⬅️ К проекту", f"ap:{project.id}") in buttons(listing.reply_markup)
    assert ("Anvar Karimov — +998901234567", f"au:11:p{project.id}") in buttons(
        listing.reply_markup
    )
    calls = await h.press(ADMIN_ID, f"au:11:p{project.id}")
    card = next(c for c in calls if isinstance(c, methods.EditMessageText))
    assert ("⬅️ К проекту", f"ap:{project.id}") in buttons(card.reply_markup)

    # Обычному пользователю админские экраны недоступны.
    assert await h.send(11, "/users") == []


async def test_admin_edits_project(harness, data, session_factory):
    project, _ = data
    h = harness

    await h.press(ADMIN_ID, f"ap_edit:{project.id}:title")
    calls = await h.send(ADMIN_ID, "Hub Project 2026")
    assert "Название обновлено" in sent_texts(calls)
    assert "Hub Project 2026" in calls[-1].text

    photo = [PhotoSize(file_id="NEW_PHOTO", file_unique_id="p", width=10, height=10)]
    await h.press(ADMIN_ID, f"ap_edit:{project.id}:content")
    assert "Описание обновлено" in sent_texts(
        await h.send(ADMIN_ID, photo=photo, caption="Новое описание")
    )

    await h.press(ADMIN_ID, f"ap_edit:{project.id}:req")
    assert "Сохранено" in sent_texts(await h.press(ADMIN_ID, f"ap_setreq:{project.id}:both"))

    async with session_factory() as s:
        updated = await repo.get_project(s, project.id)
    assert updated.title == "Hub Project 2026"
    assert updated.description == "Новое описание" and updated.photo_file_id == "NEW_PHOTO"
    assert updated.require_cv and updated.require_letter

    # Пользователь видит обновлённую карточку.
    calls = await h.press(11, f"prj:{project.id}")
    card = next(c for c in calls if isinstance(c, methods.SendPhoto))
    assert card.photo == "NEW_PHOTO" and "Hub Project 2026" in card.caption


async def test_admin_edits_contest_and_extends_links(harness, data, session_factory):
    _, contest = data
    h = harness

    await h.press(ADMIN_ID, f"ac_edit:{contest.id}:title")
    assert "Название обновлено" in sent_texts(await h.send(ADMIN_ID, "Invite Race 2.0"))

    new_end = (utcnow() + timedelta(days=30)).astimezone(TASHKENT)
    await h.press(ADMIN_ID, f"ac_edit:{contest.id}:ends")
    calls = await h.send(ADMIN_ID, new_end.strftime("%d.%m.%Y %H:%M"))
    out = sent_texts(calls)
    assert "Ссылок продлено: 1" in out and "не удалось" not in out
    # Выданная ранее ссылка получает новый срок жизни, иначе она умрёт по старой дате.
    edit = next(c for c in calls if isinstance(c, methods.EditChatInviteLink))
    assert edit.invite_link == "https://t.me/+one" and edit.chat_id == CHANNEL_ID

    async with session_factory() as s:
        updated = await repo.get_contest(s, contest.id)
    assert updated.title == "Invite Race 2.0"
    assert updated.ends_at.astimezone(TASHKENT).strftime("%d.%m.%Y %H:%M") == (
        new_end.strftime("%d.%m.%Y %H:%M")
    )

    # Прошедшую дату не принимаем.
    await h.press(ADMIN_ID, f"ac_edit:{contest.id}:ends")
    assert "в будущем" in sent_texts(await h.send(ADMIN_ID, "01.01.2020 10:00"))

    # Участники конкурса — списком, с переходом в карточку человека.
    calls = await h.press(ADMIN_ID, f"ac_parts:{contest.id}:0")
    listing = next(c for c in calls if isinstance(c, methods.EditMessageText))
    assert ("Anvar Karimov — приглашено 0", f"au:11:c{contest.id}") in buttons(
        listing.reply_markup
    )
    calls = await h.press(ADMIN_ID, f"au:11:c{contest.id}")
    card = next(c for c in calls if isinstance(c, methods.EditMessageText))
    assert ("⬅️ К конкурсу", f"ac:{contest.id}") in buttons(card.reply_markup)


async def test_usernames_are_tracked_and_shown(harness, data, session_factory):
    h = harness

    # Username подхватывается при любом обращении к боту, в том числе у старых пользователей.
    h.usernames[11] = "anvar_k"
    await h.send(11, "/start")

    calls = await h.send(ADMIN_ID, "/users")
    assert ("Anvar Karimov (@anvar_k) — +998901234567", "au:11:u") in buttons(
        calls[-1].reply_markup
    )
    calls = await h.send(ADMIN_ID, "/users @anvar")
    assert "Найдено по «@anvar»: 1" in calls[-1].text

    calls = await h.press(ADMIN_ID, "au:11:u")
    card = next(c for c in calls if isinstance(c, methods.EditMessageText))
    assert "@anvar_k" in card.text

    calls = await h.press(ADMIN_ID, "au_csv")
    csv = next(c for c in calls if isinstance(c, methods.SendDocument))
    assert "@anvar_k" in csv.document.data.decode("utf-8-sig")

    assert "Anvar Karimov (@anvar_k)" in sent_texts(await h.send(ADMIN_ID, "/message @ANVAR_K"))
    await h.send(ADMIN_ID, "/cancel")
    assert "не найден" in sent_texts(await h.send(ADMIN_ID, "/message abc"))

    # Сменил username — обновляем; убрал — очищаем.
    h.usernames[11] = "anvar_new"
    await h.send(11, "/start")
    async with session_factory() as s:
        assert (await repo.get_user(s, 11)).username == "anvar_new"
    del h.usernames[11]
    await h.send(11, "/start")
    async with session_factory() as s:
        assert (await repo.get_user(s, 11)).username is None
