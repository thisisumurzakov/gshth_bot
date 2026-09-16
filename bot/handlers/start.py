from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot import keyboards
from bot.db.models import User
from bot.handlers.flows import send_language_prompt, send_next_step
from bot.handlers.registration import ask_profile
from bot.locales import t

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, user: User | None) -> None:
    await state.clear()
    if user is None:
        await send_language_prompt(message.bot, message.chat.id)
    elif not user.profile_complete:
        await ask_profile(message.bot, user, state)
    else:
        await send_next_step(message.bot, user)


# Кнопка из инлайн-меню прежней версии бота — у старых пользователей она ещё в истории.
@router.callback_query(F.data == "change_lang")
async def cb_change_language(callback: CallbackQuery, user: User | None) -> None:
    await callback.answer()
    if user is not None:
        await callback.message.answer(
            t(user.language, "btn_change_language"),
            reply_markup=keyboards.language_kb(),
        )
