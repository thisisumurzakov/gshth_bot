"""Сквозные сценарии: регистрация, анкета для старых пользователей, заявки на
проекты, ссылки конкурсов и порядок роутеров."""

from datetime import date, timedelta

from aiogram import methods
from aiogram.types import Contact, Document, PhotoSize

from bot.db import repo
from bot.db.models import User, utcnow

from tests.helpers import ADMIN_ID, CHANNEL_ID, sent_texts


async def test_bot_flows(harness, session_factory):
    h = harness

    # --- Старый пользователь без новых полей: любое действие ведёт в анкету. ---
    async with session_factory() as s:
        s.add(
            User(
                tg_id=1, full_name="Old User", phone="+998901", language="ru",
                subscribed_at=utcnow(),
            )
        )
        await s.commit()

    out = sent_texts(await h.send(1, "📂 Проекты"))
    assert "дополните данные" in out and "дату рождения" in out
    out = sent_texts(await h.send(1, "32.13.2000"))
    assert "Дата не распознана" in out
    out = sent_texts(await h.send(1, "15.03.2002"))
    assert "учитесь или работаете" in out
    out = sent_texts(await h.send(1, "Westminster International University"))
    assert "данные сохранены" in out and "выберите раздел" in out
    async with session_factory() as s:
        user = await repo.get_user(s, 1)
        assert user.birth_date == date(2002, 3, 15)
        assert user.workplace == "Westminster International University"

    # --- Новый пользователь: полная регистрация, затем подписка → меню. ---
    h.usernames[2] = "john_smith"
    out = sent_texts(await h.send(2, "/start"))
    assert "Choose a language" in out
    out = sent_texts(await h.press(2, "setlang:en"))
    assert "first and last name" in out
    await h.send(2, "John Smith")
    out = sent_texts(
        await h.send(2, contact=Contact(phone_number="998901234567", first_name="J", user_id=2))
    )
    assert "date of birth" in out
    # /start посреди анкеты не принимается за ответ.
    out = sent_texts(await h.send(2, "/start"))
    assert "date of birth" in out and "isn't valid" not in out
    await h.send(2, "01.01.2000")
    out = sent_texts(await h.send(2, "TUIT"))
    assert "registration is complete" in out and "subscribe" in out
    out = sent_texts(await h.press(2, "check_sub"))
    assert "Subscription confirmed" in out
    async with session_factory() as s:
        user = await repo.get_user(s, 2)
        assert user.phone == "+998901234567" and user.profile_complete
        assert user.username == "john_smith"
        assert user.subscribed_at is not None

    # --- Проект с CV и письмом. ---
    async with session_factory() as s:
        project = await repo.create_project(
            s, title="Hub Project", description="<b>About</b>",
            require_cv=True, require_letter=True,
        )
        hidden = await repo.create_project(s, title="Hidden", description="x", is_active=False)

    calls = await h.send(2, "📂 Projects")
    kb = calls[-1].reply_markup.inline_keyboard
    assert [row[0].text for row in kb] == ["Hub Project"]
    out = sent_texts(await h.press(2, f"prj:{hidden.id}"))
    assert "no longer available" in out
    await h.press(2, f"prj:{project.id}")
    out = sent_texts(await h.press(2, f"prj_apply:{project.id}"))
    assert "CV" in out
    out = sent_texts(await h.send(2, "here is my cv"))
    assert "as a file" in out

    # Кнопка меню посреди заявки выходит из неё.
    out = sent_texts(await h.send(2, "🏆 Contests"))
    assert "no active contests" in out
    out = sent_texts(await h.send(2, "some text"))
    assert out == ""  # состояние сброшено, текст ни во что не превращается

    await h.press(2, f"prj_apply:{project.id}")
    doc = Document(file_id="CV_FILE_ID", file_unique_id="u1", file_name="cv.pdf")
    out = sent_texts(await h.send(2, document=doc))
    assert "motivation letter" in out
    out = sent_texts(await h.send(2, "too short"))
    assert "30 to 3500" in out
    calls = await h.send(2, "I really want to join this project because " * 2)
    assert "You are registered" in sent_texts(calls)
    admin_calls = [c for c in calls if getattr(c, "chat_id", None) == ADMIN_ID]
    assert any(isinstance(c, methods.SendDocument) and c.document == "CV_FILE_ID" for c in admin_calls)
    assert "Hub Project" in sent_texts(admin_calls)
    out = sent_texts(await h.press(2, f"prj_apply:{project.id}"))
    assert "already registered" in out

    # --- Конкурс: персональная ссылка и подсчёт вступлений. ---
    async with session_factory() as s:
        contest = await repo.create_contest(
            s, title="Invite Race", description="Win a prize",
            channel_id=CHANNEL_ID, channel_title="Channel",
            ends_at=utcnow() + timedelta(days=3),
        )
    calls = await h.send(1, "🏆 Конкурсы")
    assert calls[-1].reply_markup.inline_keyboard[0][0].text == "Invite Race"
    calls = await h.press(1, f"cst_link:{contest.id}")
    create = next(c for c in calls if isinstance(c, methods.CreateChatInviteLink))
    assert create.chat_id == CHANNEL_ID and create.expire_date is not None
    async with session_factory() as s:
        link = (await repo.get_participant(s, contest.id, 1)).invite_link
    assert link in sent_texts(calls) and "Приглашено вами: 0" in sent_texts(calls)

    await h.channel_event(500, joined=True, link=link)
    await h.channel_event(501, joined=True, link=None)  # без ссылки — не считается
    await h.channel_event(502, joined=True, link=link)
    await h.channel_event(502, joined=False, link=None)  # вышел — не считается
    out = sent_texts(await h.press(1, f"cst:{contest.id}"))
    assert "Приглашено вами: 1" in out
    # Повторное нажатие не создаёт вторую ссылку.
    calls = await h.press(1, f"cst_link:{contest.id}")
    assert not any(isinstance(c, methods.CreateChatInviteLink) for c in calls)

    # Админ видит итоги.
    calls = await h.send(ADMIN_ID, "/contests")
    assert "Invite Race" in calls[-1].reply_markup.inline_keyboard[0][0].text
    calls = await h.press(ADMIN_ID, f"ac:{contest.id}")
    edit = next(c for c in calls if isinstance(c, methods.EditMessageText))
    assert "Old User" in edit.text and "— 1" in edit.text


async def test_admin_creates_project_with_photo(harness, session_factory):
    h = harness
    await h.send(ADMIN_ID, "/new_project")
    await h.send(ADMIN_ID, "Volunteer Week")
    photo = [PhotoSize(file_id="PHOTO_ID", file_unique_id="p", width=10, height=10)]
    out = sent_texts(await h.send(ADMIN_ID, photo=photo, caption="Join us"))
    assert "материалы" in out
    calls = await h.press(ADMIN_ID, "np_req:letter")
    preview = next(c for c in calls if isinstance(c, methods.SendPhoto))
    assert preview.photo == "PHOTO_ID" and "Volunteer Week" in preview.caption
    await h.press(ADMIN_ID, "np_save")

    async with session_factory() as s:
        [project] = await repo.list_projects(s, only_active=True)
    assert project.photo_file_id == "PHOTO_ID"
    assert project.require_letter and not project.require_cv

    # Обычный пользователь не может выполнять админ-команды.
    async with session_factory() as s:
        s.add(
            User(
                tg_id=3, full_name="Regular User", phone="+998903", language="ru",
                birth_date=date(2000, 1, 1), workplace="X", subscribed_at=utcnow(),
            )
        )
        await s.commit()
    await h.send(3, "/new_project")
    async with session_factory() as s:
        assert len(await repo.list_projects(s, only_active=False)) == 1


async def test_language_can_be_changed_during_profile_questions(harness, session_factory):
    h = harness
    async with session_factory() as s:
        s.add(
            User(
                tg_id=7, full_name="Old Ru", phone="+998907", language="ru",
                subscribed_at=utcnow(),
            )
        )
        await s.commit()

    # Вопрос приходит на языке из профиля — с кнопкой смены языка.
    calls = await h.send(7, "/start")
    assert "дату рождения" in calls[-1].text
    assert calls[-1].reply_markup.inline_keyboard[0][0].callback_data == "change_lang"

    out = sent_texts(await h.press(7, "change_lang"))
    assert "Сменить язык" in out
    out = sent_texts(await h.press(7, "setlang:uz"))
    assert "Til o'zgartirildi" in out and "Tug'ilgan sanangizni" in out
    assert "menyudan" not in out  # анкету не пропускаем

    # Смена языка на втором вопросе не сбрасывает уже введённую дату.
    assert "Qayerda o'qiysiz" in sent_texts(await h.send(7, "15.03.2002"))
    out = sent_texts(await h.send(7, "🌐 Tilni o'zgartirish"))
    assert "Choose a language" in out and "aniqlanmadi" not in out
    out = sent_texts(await h.press(7, "setlang:en"))
    assert "Language changed" in out and "study or work" in out
    out = sent_texts(await h.send(7, "Inha University"))
    assert "details are saved" in out

    async with session_factory() as s:
        user = await repo.get_user(s, 7)
    assert user.language == "en"
    assert user.birth_date == date(2002, 3, 15) and user.workplace == "Inha University"
