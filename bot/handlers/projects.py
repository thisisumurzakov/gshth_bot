from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot import keyboards
from bot.config import get_settings
from bot.db import repo
from bot.db.models import Project, ProjectApplication, User
from bot.handlers.flows import ensure_menu_access
from bot.locales import t
from bot.services.applications import notify_new_application
from bot.services.cards import delete_quietly, send_card

router = Router(name="projects")

LETTER_MIN_LEN = 30
LETTER_MAX_LEN = 3500


class ApplyProject(StatesGroup):
    cv = State()
    letter = State()


async def show_projects(bot: Bot, session: AsyncSession, user: User) -> None:
    projects = await repo.list_projects(session, only_active=True)
    if not projects:
        await bot.send_message(user.tg_id, t(user.language, "projects_empty"))
        return
    await bot.send_message(
        user.tg_id,
        t(user.language, "projects_list"),
        reply_markup=keyboards.projects_kb(projects),
    )


async def show_project(
    bot: Bot, session: AsyncSession, user: User, project: Project
) -> None:
    applied = await repo.get_application(session, project.id, user.tg_id) is not None
    await send_card(
        bot,
        user.tg_id,
        f"<b>{escape(project.title)}</b>\n\n{project.description}",
        project.photo_file_id,
        keyboards.project_kb(user.language, project.id, applied),
    )


async def _active_project(
    callback: CallbackQuery, session: AsyncSession, user: User
) -> Project | None:
    project = await repo.get_project(session, int(callback.data.split(":", 1)[1]))
    if project is None or not project.is_active:
        await callback.answer(t(user.language, "project_unavailable"), show_alert=True)
        return None
    return project


@router.callback_query(F.data == "prj")
async def cb_projects(
    callback: CallbackQuery, session: AsyncSession, user: User | None
) -> None:
    await callback.answer()
    if not await ensure_menu_access(callback.bot, callback.from_user.id, user):
        return
    await delete_quietly(callback.message)
    await show_projects(callback.bot, session, user)


@router.callback_query(F.data.startswith("prj:"))
async def cb_project(
    callback: CallbackQuery, session: AsyncSession, user: User | None
) -> None:
    if not await ensure_menu_access(callback.bot, callback.from_user.id, user):
        await callback.answer()
        return
    project = await _active_project(callback, session, user)
    if project is None:
        return
    await callback.answer()
    await delete_quietly(callback.message)
    await show_project(callback.bot, session, user, project)


@router.callback_query(F.data == "prj_applied")
async def cb_already_applied(callback: CallbackQuery, user: User | None) -> None:
    await callback.answer(
        t(user.language if user else None, "already_applied"), show_alert=True
    )


@router.callback_query(F.data.startswith("prj_apply:"))
async def cb_apply(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User | None
) -> None:
    if not await ensure_menu_access(callback.bot, callback.from_user.id, user):
        await callback.answer()
        return
    project = await _active_project(callback, session, user)
    if project is None:
        return
    if await repo.get_application(session, project.id, user.tg_id) is not None:
        await callback.answer(t(user.language, "already_applied"), show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await state.update_data(project_id=project.id)
    await _ask_next_or_finish(callback.bot, state, session, user, project)


@router.callback_query(F.data.startswith("prj_cancel:"))
async def cb_cancel_application(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User | None
) -> None:
    await callback.answer()
    await state.clear()
    if user is None:
        return
    await delete_quietly(callback.message)
    await callback.bot.send_message(user.tg_id, t(user.language, "application_cancelled"))
    project = await repo.get_project(session, int(callback.data.split(":", 1)[1]))
    if project is not None and project.is_active:
        await show_project(callback.bot, session, user, project)


@router.message(ApplyProject.cv, F.document)
async def process_cv(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    await state.update_data(cv_file_id=message.document.file_id)
    await _continue(message, state, session, user)


@router.message(ApplyProject.letter, F.document)
async def process_letter_file(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    await state.update_data(letter_file_id=message.document.file_id)
    await _continue(message, state, session, user)


@router.message(ApplyProject.letter, F.text & ~F.text.startswith("/"))
async def process_letter_text(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    letter = message.text.strip()
    if not LETTER_MIN_LEN <= len(letter) <= LETTER_MAX_LEN:
        await _reject(message, state, user, "letter_invalid")
        return
    await state.update_data(letter_text=letter)
    await _continue(message, state, session, user)


@router.message(ApplyProject.cv, ~F.text.startswith("/"))
async def process_cv_invalid(message: Message, state: FSMContext, user: User) -> None:
    await _reject(message, state, user, "cv_invalid")


@router.message(ApplyProject.letter, ~F.text.startswith("/"))
async def process_letter_invalid(message: Message, state: FSMContext, user: User) -> None:
    await _reject(message, state, user, "letter_invalid")


async def _reject(message: Message, state: FSMContext, user: User, key: str) -> None:
    data = await state.get_data()
    await message.answer(
        t(user.language, key),
        reply_markup=keyboards.cancel_application_kb(user.language, data["project_id"]),
    )


async def _continue(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    data = await state.get_data()
    project = await repo.get_project(session, data["project_id"])
    if project is None or not project.is_active:
        await state.clear()
        await message.answer(t(user.language, "project_unavailable"))
        return
    await _ask_next_or_finish(message.bot, state, session, user, project)


async def _ask_next_or_finish(
    bot: Bot, state: FSMContext, session: AsyncSession, user: User, project: Project
) -> None:
    """Спрашивает недостающие материалы (CV, письмо) по очереди, затем сохраняет заявку."""
    data = await state.get_data()
    lang = user.language
    cancel_kb = keyboards.cancel_application_kb(lang, project.id)
    if project.require_cv and "cv_file_id" not in data:
        await state.set_state(ApplyProject.cv)
        await bot.send_message(user.tg_id, t(lang, "ask_cv"), reply_markup=cancel_kb)
        return
    if project.require_letter and not ("letter_text" in data or "letter_file_id" in data):
        await state.set_state(ApplyProject.letter)
        await bot.send_message(user.tg_id, t(lang, "ask_letter"), reply_markup=cancel_kb)
        return

    await state.clear()
    application = ProjectApplication(
        project_id=project.id,
        tg_id=user.tg_id,
        cv_file_id=data.get("cv_file_id"),
        letter_text=data.get("letter_text"),
        letter_file_id=data.get("letter_file_id"),
    )
    session.add(application)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        await bot.send_message(user.tg_id, t(lang, "already_applied"))
        return
    await bot.send_message(
        user.tg_id, t(lang, "application_done", title=project.title)
    )
    await notify_new_application(bot, get_settings(), project, application, user)
