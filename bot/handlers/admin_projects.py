import asyncio
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db import repo
from bot.db.models import Project
from bot.services.applications import applications_csv
from bot.services.broadcast import SEND_INTERVAL
from bot.services.cards import extract_content, send_card

router = Router(name="admin_projects")
router.message.filter(F.from_user.id.in_(get_settings().admin_id_list))
router.callback_query.filter(F.from_user.id.in_(get_settings().admin_id_list))

NOT_COMMAND = ~F.text.startswith("/")
TITLE_MAX_LEN = 60

REQUIREMENTS = {
    "none": ("Без доп. материалов", False, False),
    "cv": ("Нужно CV", True, False),
    "letter": ("Нужно мотивационное письмо", False, True),
    "both": ("CV + мотивационное письмо", True, True),
}


PAGE_SIZE = 10


class EditProject(StatesGroup):
    title = State()
    content = State()


class NewProject(StatesGroup):
    title = State()
    content = State()
    requirements = State()
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


def requirements_label(require_cv: bool, require_letter: bool) -> str:
    for label, cv, letter in REQUIREMENTS.values():
        if (cv, letter) == (require_cv, require_letter):
            return label
    return ""


# --- Создание проекта ---


@router.message(Command("new_project"))
async def cmd_new_project(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(NewProject.title)
    await message.answer(
        f"Название проекта (до {TITLE_MAX_LEN} символов) — оно будет на кнопке "
        "в списке. /cancel — отмена."
    )


@router.message(NewProject.title, F.text, NOT_COMMAND)
async def new_project_title(message: Message, state: FSMContext) -> None:
    title = " ".join(message.text.split())
    if not title or len(title) > TITLE_MAX_LEN:
        await message.answer(f"Название должно быть от 1 до {TITLE_MAX_LEN} символов.")
        return
    await state.update_data(title=title)
    await state.set_state(NewProject.content)
    await message.answer(
        "Пришлите описание проекта: текстом или фото с подписью "
        "(форматирование сохранится)."
    )


@router.message(NewProject.content, NOT_COMMAND)
async def new_project_content(message: Message, state: FSMContext) -> None:
    content = extract_content(message)
    if content is None:
        await message.answer("Нужен текст или фото с подписью.")
        return
    description, photo_file_id = content
    await state.update_data(description=description, photo_file_id=photo_file_id)
    await state.set_state(NewProject.requirements)
    await message.answer(
        "Какие материалы запрашивать при регистрации?",
        reply_markup=_kb(*((label, f"np_req:{key}") for key, (label, _, _) in REQUIREMENTS.items())),
    )


@router.callback_query(NewProject.requirements, F.data.startswith("np_req:"))
async def new_project_requirements(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 1)[1]
    label, require_cv, require_letter = REQUIREMENTS[key]
    await callback.answer()
    await state.update_data(require_cv=require_cv, require_letter=require_letter)
    await state.set_state(NewProject.confirm)
    data = await state.get_data()
    await callback.message.edit_text(f"Материалы: {label}\n\nПревью карточки ⬇️")
    await send_card(
        callback.bot,
        callback.from_user.id,
        f"<b>{escape(data['title'])}</b>\n\n{data['description']}",
        data["photo_file_id"],
    )
    await callback.message.answer(
        "Опубликовать проект?",
        reply_markup=_kb(("✅ Опубликовать", "np_save"), ("❌ Отменить", "np_cancel")),
    )


@router.callback_query(NewProject.confirm, F.data == "np_save")
async def new_project_save(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    await state.clear()
    await callback.answer()
    project = await repo.create_project(
        session,
        title=data["title"],
        description=data["description"],
        photo_file_id=data["photo_file_id"],
        require_cv=data["require_cv"],
        require_letter=data["require_letter"],
    )
    await callback.message.edit_text(
        f"Проект «{project.title}» опубликован ✅ Управление — /projects"
    )


@router.callback_query(NewProject.confirm, F.data == "np_cancel")
async def new_project_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text("Создание проекта отменено.")


# --- Управление проектами ---


async def _projects_list(session: AsyncSession) -> tuple[str, InlineKeyboardMarkup | None]:
    projects = await repo.list_projects(session, only_active=False)
    if not projects:
        return "Проектов пока нет. Создать — /new_project", None
    rows = [
        (f"{'🟢' if p.is_active else '⚪'} {p.title}", f"ap:{p.id}") for p in projects
    ]
    return "Проекты (🟢 — виден пользователям, ⚪ — скрыт):", _kb(*rows)


async def _project_card(
    session: AsyncSession, project: Project
) -> tuple[str, InlineKeyboardMarkup]:
    count = await repo.application_count(session, project.id)
    text = (
        f"<b>{escape(project.title)}</b>\n"
        f"Статус: {'🟢 виден пользователям' if project.is_active else '⚪ скрыт'}\n"
        f"Материалы: {requirements_label(project.require_cv, project.require_letter)}\n"
        f"Заявок: {count}"
    )
    kb = _kb(
        [
            ("✏️ Название", f"ap_edit:{project.id}:title"),
            ("✏️ Описание", f"ap_edit:{project.id}:content"),
            ("✏️ Материалы", f"ap_edit:{project.id}:req"),
        ],
        (f"👥 Заявки списком ({count})", f"ap_apps:{project.id}:0"),
        [
            ("📥 Заявки (CSV)", f"ap_csv:{project.id}"),
            ("📎 Все файлы", f"ap_files:{project.id}"),
        ],
        ("🙈 Скрыть" if project.is_active else "👁 Показать", f"ap_toggle:{project.id}"),
        ("⬅️ К списку", "ap_list"),
    )
    return text, kb


@router.message(Command("projects"))
async def cmd_projects(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    text, kb = await _projects_list(session)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "ap_list")
async def cb_projects_list(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    text, kb = await _projects_list(session)
    await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("ap:"))
async def cb_project_card(callback: CallbackQuery, session: AsyncSession) -> None:
    project = await repo.get_project(session, int(callback.data.split(":", 1)[1]))
    if project is None:
        await callback.answer("Проект не найден", show_alert=True)
        return
    await callback.answer()
    text, kb = await _project_card(session, project)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("ap_toggle:"))
async def cb_project_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    project = await repo.get_project(session, int(callback.data.split(":", 1)[1]))
    if project is None:
        await callback.answer("Проект не найден", show_alert=True)
        return
    project.is_active = not project.is_active
    await session.commit()
    await callback.answer("Проект показан" if project.is_active else "Проект скрыт")
    text, kb = await _project_card(session, project)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("ap_csv:"))
async def cb_project_csv(callback: CallbackQuery, session: AsyncSession) -> None:
    project = await repo.get_project(session, int(callback.data.split(":", 1)[1]))
    if project is None:
        await callback.answer("Проект не найден", show_alert=True)
        return
    rows = await repo.project_applications(session, project.id)
    if not rows:
        await callback.answer("Заявок пока нет", show_alert=True)
        return
    await callback.answer()
    bot_username = (await callback.bot.me()).username
    await callback.message.answer_document(
        applications_csv(project, rows, bot_username),
        caption=f"Заявки на «{project.title}»: {len(rows)}\n"
        "Ссылки в колонках CV и «Мотивационное письмо» открывайте из аккаунта "
        "админа — бот пришлёт файл.",
    )


@router.callback_query(F.data.startswith("ap_apps:"))
async def cb_project_applications(callback: CallbackQuery, session: AsyncSession) -> None:
    """Список заявок: имя → карточка человека с его данными и файлами."""
    _, project_id, offset = callback.data.split(":", 2)
    project_id, offset = int(project_id), int(offset)
    project = await repo.get_project(session, project_id)
    if project is None:
        await callback.answer("Проект не найден", show_alert=True)
        return
    applications = await repo.project_applications(session, project_id)
    if not applications:
        await callback.answer("Заявок пока нет", show_alert=True)
        return
    await callback.answer()
    page = applications[offset : offset + PAGE_SIZE]
    rows: list = [
        (f"{user.display_name} — {user.phone}", f"au:{user.tg_id}:p{project_id}")
        for _, user in page
    ]
    nav = []
    if offset:
        nav.append(("⬅️", f"ap_apps:{project_id}:{max(offset - PAGE_SIZE, 0)}"))
    if offset + PAGE_SIZE < len(applications):
        nav.append(("➡️", f"ap_apps:{project_id}:{offset + PAGE_SIZE}"))
    if nav:
        rows.append(nav)
    rows.append(("⬅️ К проекту", f"ap:{project_id}"))
    await callback.message.edit_text(
        f"Заявки на «{escape(project.title)}»: {len(applications)}\n"
        f"Показаны {offset + 1}–{offset + len(page)}",
        parse_mode="HTML",
        reply_markup=_kb(*rows),
    )


@router.callback_query(F.data.startswith("ap_files:"))
async def cb_project_files(callback: CallbackQuery, session: AsyncSession) -> None:
    """Файлы пересылаются по file_id с серверов Telegram — бот их не хранит."""
    project = await repo.get_project(session, int(callback.data.split(":", 1)[1]))
    if project is None:
        await callback.answer("Проект не найден", show_alert=True)
        return
    files = [
        (file_id, f"{label} — {user.display_name}, {user.phone}")
        for app, user in await repo.project_applications(session, project.id)
        for file_id, label in (
            (app.cv_file_id, "CV"),
            (app.letter_file_id, "Мотивационное письмо"),
        )
        if file_id
    ]
    if not files:
        await callback.answer("Файлов в заявках нет", show_alert=True)
        return
    await callback.answer()
    for file_id, caption in files:
        await callback.message.answer_document(file_id, caption=caption)
        await asyncio.sleep(SEND_INTERVAL)


# --- Редактирование проекта ---


@router.callback_query(F.data.startswith("ap_edit:"))
async def cb_project_edit(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    _, project_id, field = callback.data.split(":", 2)
    project = await repo.get_project(session, int(project_id))
    if project is None:
        await callback.answer("Проект не найден", show_alert=True)
        return
    await callback.answer()
    if field == "req":
        await callback.message.answer(
            f"«{project.title}»: сейчас — "
            f"{requirements_label(project.require_cv, project.require_letter)}.\n"
            "Что запрашивать при регистрации?",
            reply_markup=_kb(
                *((label, f"ap_setreq:{project.id}:{key}") for key, (label, _, _) in REQUIREMENTS.items())
            ),
        )
        return
    await state.set_state(
        EditProject.title if field == "title" else EditProject.content
    )
    await state.update_data(project_id=project.id)
    prompt = (
        f"Текущее название: {project.title}\n\nПришлите новое (до {TITLE_MAX_LEN} символов)."
        if field == "title"
        else "Пришлите новое описание: текстом или фото с подписью.\n"
        "Прежнее фото заменится только если пришлёте новое."
    )
    await callback.message.answer(prompt + " /cancel — отмена.")


@router.callback_query(F.data.startswith("ap_setreq:"))
async def cb_project_set_requirements(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    _, project_id, key = callback.data.split(":", 2)
    project = await repo.get_project(session, int(project_id))
    if project is None:
        await callback.answer("Проект не найден", show_alert=True)
        return
    label, project.require_cv, project.require_letter = REQUIREMENTS[key]
    await session.commit()
    await callback.answer("Сохранено")
    await callback.message.edit_text(f"Материалы: {label}")
    await _send_card(callback.message, session, project)


@router.message(EditProject.title, F.text, NOT_COMMAND)
async def edit_project_title(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    title = " ".join(message.text.split())
    if not title or len(title) > TITLE_MAX_LEN:
        await message.answer(f"Название должно быть от 1 до {TITLE_MAX_LEN} символов.")
        return
    project = await _edited_project(message, state, session)
    if project is None:
        return
    project.title = title
    await session.commit()
    await state.clear()
    await message.answer("Название обновлено ✅")
    await _send_card(message, session, project)


@router.message(EditProject.content, NOT_COMMAND)
async def edit_project_content(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    content = extract_content(message)
    if content is None:
        await message.answer("Нужен текст или фото с подписью.")
        return
    project = await _edited_project(message, state, session)
    if project is None:
        return
    project.description, photo_file_id = content
    if photo_file_id is not None:
        project.photo_file_id = photo_file_id
    await session.commit()
    await state.clear()
    await message.answer("Описание обновлено ✅")
    await _send_card(message, session, project)


async def _edited_project(
    message: Message, state: FSMContext, session: AsyncSession
) -> Project | None:
    data = await state.get_data()
    project = await repo.get_project(session, data["project_id"])
    if project is None:
        await state.clear()
        await message.answer("Проект не найден — возможно, он был удалён.")
    return project


async def _send_card(message: Message, session: AsyncSession, project: Project) -> None:
    text, kb = await _project_card(session, project)
    await message.answer(text, parse_mode="HTML", reply_markup=kb)
