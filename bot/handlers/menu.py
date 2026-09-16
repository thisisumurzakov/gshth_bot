"""Кнопки главного меню (reply-клавиатура). Роутер подключается раньше сценариев
с состояниями, поэтому нажатие кнопки меню посреди заявки выходит из неё."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import keyboards
from bot.db.models import User
from bot.handlers.contests import show_contests
from bot.handlers.flows import ensure_menu_access
from bot.handlers.projects import show_projects
from bot.locales import all_variants, t

router = Router(name="menu")


@router.message(F.text.in_(all_variants("btn_projects")))
async def menu_projects(
    message: Message, state: FSMContext, session: AsyncSession, user: User | None
) -> None:
    await state.clear()
    if await ensure_menu_access(message.bot, message.chat.id, user):
        await show_projects(message.bot, session, user)


@router.message(F.text.in_(all_variants("btn_contests")))
async def menu_contests(
    message: Message, state: FSMContext, session: AsyncSession, user: User | None
) -> None:
    await state.clear()
    if await ensure_menu_access(message.bot, message.chat.id, user):
        await show_contests(message.bot, session, user)


@router.message(F.text.in_(all_variants("btn_change_language")))
async def menu_change_language(
    message: Message, state: FSMContext, user: User | None
) -> None:
    await state.clear()
    await message.answer(
        t(user.language if user else None, "btn_change_language"),
        reply_markup=keyboards.language_kb(),
    )
