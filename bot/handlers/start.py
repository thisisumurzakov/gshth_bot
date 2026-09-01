from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import keyboards
from bot.config import get_settings
from bot.db.models import User
from bot.handlers.flows import send_menu, send_subscribe_prompt
from bot.handlers.registration import start_registration
from bot.locales import t

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(
    message: Message, state: FSMContext, session: AsyncSession, user: User | None
) -> None:
    await state.clear()
    settings = get_settings()
    if user is None:
        await start_registration(message, state)
    elif user.invite_link is None:
        # Зарегистрирован, но подписку так и не подтвердил — продолжаем с этого шага.
        await send_subscribe_prompt(message.bot, user.tg_id, user.language, settings)
    else:
        await send_menu(message.bot, session, user, settings)


@router.callback_query(F.data == "change_lang")
async def cb_change_language(callback: CallbackQuery, user: User | None) -> None:
    await callback.answer()
    if user is not None:
        await callback.message.answer(
            t(user.language, "btn_change_language"),
            reply_markup=keyboards.language_kb(),
        )
