from datetime import datetime
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MessageOriginChannel,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db import repo
from bot.db.models import Contest, utcnow
from bot.handlers.contests import contest_text
from bot.services.applications import contest_csv
from bot.services.cards import extract_content, send_card
from bot.services.contests import reschedule_links
from bot.services.timeutil import format_local_datetime, parse_local_datetime

router = Router(name="admin_contests")
router.message.filter(F.from_user.id.in_(get_settings().admin_id_list))
router.callback_query.filter(F.from_user.id.in_(get_settings().admin_id_list))

NOT_COMMAND = ~F.text.startswith("/")
TITLE_MAX_LEN = 60
TOP_SIZE = 10
PAGE_SIZE = 10


class EditContest(StatesGroup):
    title = State()
    content = State()
    ends_at = State()


class NewContest(StatesGroup):
    channel = State()
    title = State()
    content = State()
    ends_at = State()
    confirm = State()


def _kb(*rows) -> InlineKeyboardMarkup:
    """Каждый ряд — (текст, callback_data) или список таких пар."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=text, callback_data=data)
                for text, data in (row if isinstance(row, list) else [row])
            ]
            for row in rows
        ]
    )


async def _resolve_channel(bot: Bot, message: Message) -> Chat | str:
    """Канал из пересланного поста, @username или ID. Возвращает Chat или текст ошибки."""
    if isinstance(message.forward_origin, MessageOriginChannel):
        ref: int | str = message.forward_origin.chat.id
    elif message.text and not message.text.startswith("/"):
        raw = message.text.strip()
        ref = int(raw) if raw.lstrip("-").isdigit() else raw
    else:
        return "Перешлите пост из канала или пришлите его @username / ID."
    try:
        chat = await bot.get_chat(ref)
        me = await bot.get_chat_member(chat.id, bot.id)
    except (TelegramBadRequest, TelegramForbiddenError):
        return (
            "Не удалось найти канал. Убедитесь, что бот добавлен в него администратором, "
            "и попробуйте ещё раз."
        )
    if chat.type not in (ChatType.CHANNEL, ChatType.SUPERGROUP):
        return "Это не канал и не группа."
    if me.status != ChatMemberStatus.ADMINISTRATOR or not getattr(
        me, "can_invite_users", False
    ):
        return (
            "Бот должен быть администратором канала с правом «Приглашать пользователей» "
            "— иначе он не сможет выдавать ссылки и считать вступления."
        )
    return chat


# --- Создание конкурса ---


@router.message(Command("new_contest"))
async def cmd_new_contest(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(NewContest.channel)
    await message.answer(
        "В какой канал приглашать участников? Перешлите сюда любой пост из канала "
        "или пришлите его @username / ID.\n\n"
        "Бот должен быть администратором канала с правом «Приглашать пользователей». "
        "/cancel — отмена."
    )


@router.message(NewContest.channel, NOT_COMMAND)
async def new_contest_channel(message: Message, state: FSMContext) -> None:
    result = await _resolve_channel(message.bot, message)
    if isinstance(result, str):
        await message.answer(result)
        return
    await state.update_data(channel_id=result.id, channel_title=result.title or str(result.id))
    await state.set_state(NewContest.title)
    await message.answer(
        f"Канал: {result.title}\n\n"
        f"Название конкурса (до {TITLE_MAX_LEN} символов) — оно будет на кнопке."
    )


@router.message(NewContest.title, F.text, NOT_COMMAND)
async def new_contest_title(message: Message, state: FSMContext) -> None:
    title = " ".join(message.text.split())
    if not title or len(title) > TITLE_MAX_LEN:
        await message.answer(f"Название должно быть от 1 до {TITLE_MAX_LEN} символов.")
        return
    await state.update_data(title=title)
    await state.set_state(NewContest.content)
    await message.answer(
        "Пришлите описание конкурса (условия, призы): текстом или фото с подписью."
    )


@router.message(NewContest.content, NOT_COMMAND)
async def new_contest_content(message: Message, state: FSMContext) -> None:
    content = extract_content(message)
    if content is None:
        await message.answer("Нужен текст или фото с подписью.")
        return
    description, photo_file_id = content
    await state.update_data(description=description, photo_file_id=photo_file_id)
    await state.set_state(NewContest.ends_at)
    await message.answer(
        "Дата и время окончания по Ташкенту в формате ДД.ММ.ГГГГ ЧЧ:ММ, "
        "например 30.09.2026 18:00"
    )


@router.message(NewContest.ends_at, F.text, NOT_COMMAND)
async def new_contest_ends_at(message: Message, state: FSMContext) -> None:
    ends_at = parse_local_datetime(message.text)
    if ends_at is None:
        await message.answer("Формат: ДД.ММ.ГГГГ ЧЧ:ММ, например 30.09.2026 18:00")
        return
    if ends_at <= utcnow():
        await message.answer("Дата окончания должна быть в будущем.")
        return
    await state.update_data(ends_at=ends_at.isoformat())
    await state.set_state(NewContest.confirm)
    data = await state.get_data()
    preview = Contest(
        title=data["title"], description=data["description"], ends_at=ends_at
    )
    await message.answer(f"Канал: {data['channel_title']}\n\nПревью карточки ⬇️")
    await send_card(
        message.bot, message.chat.id, contest_text("ru", preview), data["photo_file_id"]
    )
    await message.answer(
        "Опубликовать конкурс?",
        reply_markup=_kb(("✅ Опубликовать", "nc_save"), ("❌ Отменить", "nc_cancel")),
    )


@router.callback_query(NewContest.confirm, F.data == "nc_save")
async def new_contest_save(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    await state.clear()
    await callback.answer()
    contest = await repo.create_contest(
        session,
        title=data["title"],
        description=data["description"],
        photo_file_id=data["photo_file_id"],
        channel_id=data["channel_id"],
        channel_title=data["channel_title"],
        ends_at=datetime.fromisoformat(data["ends_at"]),
    )
    await callback.message.edit_text(
        f"Конкурс «{contest.title}» опубликован ✅ Итоги — /contests"
    )


@router.callback_query(NewContest.confirm, F.data == "nc_cancel")
async def new_contest_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text("Создание конкурса отменено.")


# --- Управление конкурсами ---


def _status(contest: Contest) -> str:
    if not contest.is_active:
        return "⚪ скрыт"
    if contest.ends_at <= utcnow():
        return "🏁 завершён"
    return "🟢 идёт"


async def _contests_list(session: AsyncSession) -> tuple[str, InlineKeyboardMarkup | None]:
    contests = await repo.list_contests(session)
    if not contests:
        return "Конкурсов пока нет. Создать — /new_contest", None
    rows = [
        (f"{_status(c).split()[0]} {c.title}", f"ac:{c.id}") for c in contests
    ]
    return "Конкурсы (🟢 идёт, 🏁 завершён, ⚪ скрыт):", _kb(*rows)


async def _contest_card(
    session: AsyncSession, contest: Contest
) -> tuple[str, InlineKeyboardMarkup]:
    participants, joins = await repo.contest_totals(session, contest.id)
    ranking = await repo.contest_ranking(session, contest.id, limit=TOP_SIZE)
    lines = [
        f"<b>{escape(contest.title)}</b>",
        f"Канал: {escape(contest.channel_title)}",
        f"Окончание: {format_local_datetime(contest.ends_at)} (Ташкент)",
        f"Статус: {_status(contest)}",
        f"Участников со ссылкой: {participants}",
        f"Приглашено всего: {joins}",
    ]
    if ranking:
        lines.append(f"\n<b>Топ-{TOP_SIZE}</b> (вышедшие из канала не считаются):")
        lines += [
            f'{place}. <a href="tg://user?id={user.tg_id}">{escape(user.full_name)}</a>'
            f" ({escape(user.phone)}) — {count}"
            for place, (user, count) in enumerate(ranking, start=1)
        ]
    kb = _kb(
        [
            ("✏️ Название", f"ac_edit:{contest.id}:title"),
            ("✏️ Описание", f"ac_edit:{contest.id}:content"),
            ("✏️ Дата", f"ac_edit:{contest.id}:ends"),
        ],
        (f"👥 Участники списком ({participants})", f"ac_parts:{contest.id}:0"),
        [
            ("📥 Все участники (CSV)", f"ac_csv:{contest.id}"),
            ("🔄 Обновить", f"ac:{contest.id}"),
        ],
        ("🙈 Скрыть" if contest.is_active else "👁 Показать", f"ac_toggle:{contest.id}"),
        ("⬅️ К списку", "ac_list"),
    )
    return "\n".join(lines), kb


async def _edit_card(callback: CallbackQuery, session: AsyncSession, contest: Contest) -> None:
    text, kb = await _contest_card(session, contest)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest:
        pass  # «message is not modified» при повторном «Обновить»


@router.message(Command("contests"))
async def cmd_contests(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    text, kb = await _contests_list(session)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "ac_list")
async def cb_contests_list(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    text, kb = await _contests_list(session)
    await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("ac:"))
async def cb_contest_card(callback: CallbackQuery, session: AsyncSession) -> None:
    contest = await repo.get_contest(session, int(callback.data.split(":", 1)[1]))
    if contest is None:
        await callback.answer("Конкурс не найден", show_alert=True)
        return
    await callback.answer()
    await _edit_card(callback, session, contest)


@router.callback_query(F.data.startswith("ac_toggle:"))
async def cb_contest_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    contest = await repo.get_contest(session, int(callback.data.split(":", 1)[1]))
    if contest is None:
        await callback.answer("Конкурс не найден", show_alert=True)
        return
    contest.is_active = not contest.is_active
    await session.commit()
    await callback.answer(
        "Конкурс показан" if contest.is_active else "Конкурс скрыт, вступления не считаются"
    )
    await _edit_card(callback, session, contest)


@router.callback_query(F.data.startswith("ac_parts:"))
async def cb_contest_participants(callback: CallbackQuery, session: AsyncSession) -> None:
    """Список участников: имя → карточка человека с его данными и заявками."""
    _, contest_id, offset = callback.data.split(":", 2)
    contest_id, offset = int(contest_id), int(offset)
    contest = await repo.get_contest(session, contest_id)
    if contest is None:
        await callback.answer("Конкурс не найден", show_alert=True)
        return
    total, _ = await repo.contest_totals(session, contest_id)
    page = await repo.contest_ranking(session, contest_id, limit=PAGE_SIZE, offset=offset)
    if not page:
        await callback.answer("Участников пока нет", show_alert=True)
        return
    await callback.answer()
    rows: list = [
        (f"{user.full_name} — приглашено {count}", f"au:{user.tg_id}:c{contest_id}")
        for user, count in page
    ]
    nav = []
    if offset:
        nav.append(("⬅️", f"ac_parts:{contest_id}:{max(offset - PAGE_SIZE, 0)}"))
    if offset + PAGE_SIZE < total:
        nav.append(("➡️", f"ac_parts:{contest_id}:{offset + PAGE_SIZE}"))
    if nav:
        rows.append(nav)
    rows.append(("⬅️ К конкурсу", f"ac:{contest_id}"))
    await callback.message.edit_text(
        f"Участники «{escape(contest.title)}»: {total}\n"
        f"Показаны {offset + 1}–{offset + len(page)} (по убыванию приглашённых)",
        parse_mode="HTML",
        reply_markup=_kb(*rows),
    )


@router.callback_query(F.data.startswith("ac_csv:"))
async def cb_contest_csv(callback: CallbackQuery, session: AsyncSession) -> None:
    contest = await repo.get_contest(session, int(callback.data.split(":", 1)[1]))
    if contest is None:
        await callback.answer("Конкурс не найден", show_alert=True)
        return
    ranking = await repo.contest_ranking(session, contest.id)
    if not ranking:
        await callback.answer("Участников пока нет", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer_document(
        contest_csv(contest.id, ranking),
        caption=f"Участники конкурса «{contest.title}»: {len(ranking)}",
    )


# --- Редактирование конкурса ---

EDIT_STATES = {
    "title": EditContest.title,
    "content": EditContest.content,
    "ends": EditContest.ends_at,
}

EDIT_PROMPTS = {
    "title": f"Пришлите новое название (до {TITLE_MAX_LEN} символов).",
    "content": (
        "Пришлите новое описание: текстом или фото с подписью. "
        "Прежнее фото заменится только если пришлёте новое."
    ),
    "ends": (
        "Пришлите новую дату окончания по Ташкенту в формате ДД.ММ.ГГГГ ЧЧ:ММ. "
        "Уже выданные участникам ссылки я продлю автоматически."
    ),
}


@router.callback_query(F.data.startswith("ac_edit:"))
async def cb_contest_edit(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    _, contest_id, field = callback.data.split(":", 2)
    contest = await repo.get_contest(session, int(contest_id))
    if contest is None:
        await callback.answer("Конкурс не найден", show_alert=True)
        return
    await callback.answer()
    await state.set_state(EDIT_STATES[field])
    await state.update_data(contest_id=contest.id)
    await callback.message.answer(EDIT_PROMPTS[field] + " /cancel — отмена.")


@router.message(EditContest.title, F.text, NOT_COMMAND)
async def edit_contest_title(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    title = " ".join(message.text.split())
    if not title or len(title) > TITLE_MAX_LEN:
        await message.answer(f"Название должно быть от 1 до {TITLE_MAX_LEN} символов.")
        return
    contest = await _edited_contest(message, state, session)
    if contest is None:
        return
    contest.title = title
    await session.commit()
    await state.clear()
    await message.answer("Название обновлено ✅")
    await _send_card(message, session, contest)


@router.message(EditContest.content, NOT_COMMAND)
async def edit_contest_content(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    content = extract_content(message)
    if content is None:
        await message.answer("Нужен текст или фото с подписью.")
        return
    contest = await _edited_contest(message, state, session)
    if contest is None:
        return
    contest.description, photo_file_id = content
    if photo_file_id is not None:
        contest.photo_file_id = photo_file_id
    await session.commit()
    await state.clear()
    await message.answer("Описание обновлено ✅")
    await _send_card(message, session, contest)


@router.message(EditContest.ends_at, F.text, NOT_COMMAND)
async def edit_contest_ends_at(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    ends_at = parse_local_datetime(message.text)
    if ends_at is None:
        await message.answer("Формат: ДД.ММ.ГГГГ ЧЧ:ММ, например 30.09.2026 18:00")
        return
    if ends_at <= utcnow():
        await message.answer("Дата окончания должна быть в будущем.")
        return
    contest = await _edited_contest(message, state, session)
    if contest is None:
        return
    contest.ends_at = ends_at
    await session.commit()
    await state.clear()
    await message.answer(
        f"Новая дата: {format_local_datetime(ends_at)} (Ташкент). Продлеваю ссылки…"
    )
    updated, failed = await reschedule_links(message.bot, session, contest)
    await message.answer(
        f"Ссылок продлено: {updated}"
        + (f", не удалось: {failed} (проверьте права бота в канале)" if failed else "")
    )
    await _send_card(message, session, contest)


async def _edited_contest(
    message: Message, state: FSMContext, session: AsyncSession
) -> Contest | None:
    data = await state.get_data()
    contest = await repo.get_contest(session, data["contest_id"])
    if contest is None:
        await state.clear()
        await message.answer("Конкурс не найден — возможно, он был удалён.")
    return contest


async def _send_card(message: Message, session: AsyncSession, contest: Contest) -> None:
    text, kb = await _contest_card(session, contest)
    await message.answer(text, parse_mode="HTML", reply_markup=kb)
