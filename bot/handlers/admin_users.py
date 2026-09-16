"""Просмотр зарегистрированных пользователей, их заявок и присланных файлов."""

import asyncio
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db import repo
from bot.db.models import User
from bot.handlers.admin import AdminStates
from bot.services.applications import user_summary_html, users_csv
from bot.services.broadcast import SEND_INTERVAL
from bot.services.timeutil import format_local_datetime

router = Router(name="admin_users")
router.message.filter(F.from_user.id.in_(get_settings().admin_id_list))
router.callback_query.filter(F.from_user.id.in_(get_settings().admin_id_list))

PAGE_SIZE = 10
QUERY_MAX_LEN = 20  # callback_data ограничена 64 байтами


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


async def users_page(
    session: AsyncSession, query: str, offset: int
) -> tuple[str, InlineKeyboardMarkup]:
    total = await repo.count_users(session, query)
    users = await repo.list_users(session, query, offset=offset, limit=PAGE_SIZE)
    if not users:
        header = (
            f"По запросу «{query}» никого не нашлось."
            if query
            else "Зарегистрированных пользователей пока нет."
        )
        return header, _kb(("🔄 Все пользователи", "au_page:0:"))
    header = (
        f"Найдено по «{query}»: {total}" if query else f"Зарегистрировано: {total}"
    )
    rows: list = [
        (f"{user.full_name} — {user.phone}", f"au:{user.tg_id}:u") for user in users
    ]
    nav = []
    if offset:
        nav.append(("⬅️", f"au_page:{max(offset - PAGE_SIZE, 0)}:{query}"))
    if offset + PAGE_SIZE < total:
        nav.append(("➡️", f"au_page:{offset + PAGE_SIZE}:{query}"))
    if nav:
        rows.append(nav)
    rows.append(("📥 Все пользователи (CSV)", "au_csv"))
    shown = f"{offset + 1}–{offset + len(users)} из {total}"
    return f"{header}\n{shown}\n\nПоиск: /users Иванов или /users 901234567", _kb(*rows)


async def user_card(
    session: AsyncSession, user: User, back: str
) -> tuple[str, InlineKeyboardMarkup]:
    lines = [
        user_summary_html(user),
        f"🌐 Язык: {user.language}",
        f"📅 Регистрация: {format_local_datetime(user.created_at)}",
        "📢 Подписка: "
        + (
            format_local_datetime(user.subscribed_at)
            if user.subscribed_at
            else "не подтверждена"
        ),
    ]
    applications = await repo.user_applications(session, user.tg_id)
    if applications:
        lines.append("\n<b>Заявки на проекты</b>")
        for app, project in applications:
            materials = ", ".join(
                filter(
                    None,
                    [
                        "CV" if app.cv_file_id else "",
                        "письмо файлом" if app.letter_file_id else "",
                        "письмо текстом" if app.letter_text else "",
                    ],
                )
            )
            lines.append(
                f"• {escape(project.title)} — {format_local_datetime(app.created_at)}"
                + (f" ({materials})" if materials else "")
            )
    contests = await repo.user_contests(session, user.tg_id)
    if contests:
        lines.append("\n<b>Конкурсы</b>")
        lines += [
            f"• {escape(contest.title)} — приглашено {count}"
            for contest, count in contests
        ]
    if not applications and not contests:
        lines.append("\nЗаявок и участий в конкурсах нет.")

    rows: list = []
    if any(app.cv_file_id or app.letter_file_id for app, _ in applications):
        rows.append(("📎 Прислать файлы заявок", f"au_files:{user.tg_id}"))
    if any(app.letter_text for app, _ in applications):
        rows.append(("✉️ Показать письма", f"au_letters:{user.tg_id}"))
    rows.append(("✉️ Написать сообщение", f"au_dm:{user.tg_id}"))
    # Откуда пришли: p{id} — карточка проекта, c{id} — конкурса, иначе список людей.
    if back.startswith("p"):
        rows.append(("⬅️ К проекту", f"ap:{back[1:]}"))
    elif back.startswith("c"):
        rows.append(("⬅️ К конкурсу", f"ac:{back[1:]}"))
    else:
        rows.append(("⬅️ К списку", "au_page:0:"))
    return "\n".join(lines), _kb(*rows)


@router.message(Command("users"))
async def cmd_users(
    message: Message, command: CommandObject, state: FSMContext, session: AsyncSession
) -> None:
    await state.clear()
    query = (command.args or "").strip()[:QUERY_MAX_LEN]
    text, kb = await users_page(session, query, offset=0)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("au_page:"))
async def cb_users_page(callback: CallbackQuery, session: AsyncSession) -> None:
    _, offset, query = callback.data.split(":", 2)
    await callback.answer()
    text, kb = await users_page(session, query, offset=int(offset))
    await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("au:"))
async def cb_user_card(callback: CallbackQuery, session: AsyncSession) -> None:
    _, tg_id, back = callback.data.split(":", 2)
    user = await repo.get_user(session, int(tg_id))
    if user is None:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    await callback.answer()
    text, kb = await user_card(session, user, back)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("au_files:"))
async def cb_user_files(callback: CallbackQuery, session: AsyncSession) -> None:
    """Файлы отдаются по file_id с серверов Telegram — бот их не хранит."""
    tg_id = int(callback.data.split(":", 1)[1])
    files = [
        (file_id, f"{label} — {escape(project.title)}")
        for app, project in await repo.user_applications(session, tg_id)
        for file_id, label in (
            (app.cv_file_id, "CV"),
            (app.letter_file_id, "Мотивационное письмо"),
        )
        if file_id
    ]
    if not files:
        await callback.answer("Файлов нет", show_alert=True)
        return
    await callback.answer()
    for file_id, caption in files:
        await callback.message.answer_document(file_id, caption=caption)
        await asyncio.sleep(SEND_INTERVAL)


@router.callback_query(F.data.startswith("au_letters:"))
async def cb_user_letters(callback: CallbackQuery, session: AsyncSession) -> None:
    tg_id = int(callback.data.split(":", 1)[1])
    letters = [
        (project.title, app.letter_text)
        for app, project in await repo.user_applications(session, tg_id)
        if app.letter_text
    ]
    if not letters:
        await callback.answer("Писем текстом нет", show_alert=True)
        return
    await callback.answer()
    for title, letter in letters:
        await callback.message.answer(
            f"✉️ <b>{escape(title)}</b>\n\n{escape(letter)}", parse_mode="HTML"
        )
        await asyncio.sleep(SEND_INTERVAL)


@router.callback_query(F.data.startswith("au_dm:"))
async def cb_user_dm(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Дальше сообщение уходит через тот же сценарий, что и /message."""
    user = await repo.get_user(session, int(callback.data.split(":", 1)[1]))
    if user is None:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminStates.direct_content)
    await state.update_data(target_tg_id=user.tg_id)
    await callback.message.answer(
        f"Получатель: {user.full_name} ({user.phone}).\n"
        "Пришлите сообщение — я отправлю его этому пользователю. /cancel — отмена."
    )


@router.callback_query(F.data == "au_csv")
async def cb_users_csv(callback: CallbackQuery, session: AsyncSession) -> None:
    users = await repo.all_users(session)
    if not users:
        await callback.answer("Пользователей нет", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer_document(
        users_csv(users), caption=f"Зарегистрированные пользователи: {len(users)}"
    )
