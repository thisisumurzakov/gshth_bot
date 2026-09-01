import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from bot import keyboards
from bot.config import get_settings
from bot.db import repo
from bot.db.models import User
from bot.handlers.flows import send_menu, send_subscribe_prompt
from bot.locales import LANGS, t

router = Router(name="registration")

PHONE_RE = re.compile(r"^\+?\d{9,15}$")

CHOOSE_LANGUAGE_PROMPT = (
    "Tilni tanlang / Выберите язык / Choose a language:"
)


class Registration(StatesGroup):
    full_name = State()
    phone = State()


async def start_registration(message: Message, state: FSMContext) -> None:
    await message.answer(CHOOSE_LANGUAGE_PROMPT, reply_markup=keyboards.language_kb())


@router.callback_query(F.data.startswith("setlang:"))
async def cb_set_language(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User | None,
) -> None:
    lang = callback.data.split(":", 1)[1]
    if lang not in LANGS:
        await callback.answer()
        return
    await callback.answer()
    if user is not None:
        # Смена языка из меню уже зарегистрированного пользователя.
        user.language = lang
        await session.commit()
        await callback.message.answer(t(lang, "language_changed"))
        if user.invite_link is None:
            await send_subscribe_prompt(callback.bot, user.tg_id, lang, get_settings())
        else:
            await send_menu(callback.bot, session, user, get_settings())
        return
    await state.update_data(language=lang)
    await state.set_state(Registration.full_name)
    await callback.message.answer(t(lang, "ask_full_name"))


@router.message(Registration.full_name, F.text)
async def process_full_name(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data["language"]
    full_name = " ".join(message.text.split())
    if len(full_name.split()) < 2 or len(full_name) > 100:
        await message.answer(t(lang, "full_name_invalid"))
        return
    await state.update_data(full_name=full_name)
    await state.set_state(Registration.phone)
    await message.answer(t(lang, "ask_phone"), reply_markup=keyboards.contact_kb(lang))


@router.message(Registration.phone, F.contact | F.text)
async def process_phone(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    lang = data["language"]

    if message.contact is not None:
        phone = message.contact.phone_number
    else:
        phone = re.sub(r"[ \-()]", "", message.text or "")
        if not PHONE_RE.match(phone):
            await message.answer(t(lang, "phone_invalid"))
            return
    if not phone.startswith("+"):
        phone = "+" + phone

    await repo.create_user(
        session,
        tg_id=message.from_user.id,
        full_name=data["full_name"],
        phone=phone,
        language=lang,
    )
    await state.clear()
    await message.answer(t(lang, "registered"), reply_markup=ReplyKeyboardRemove())
    settings = get_settings()
    await message.answer(
        t(lang, "subscribe_prompt"),
        reply_markup=keyboards.subscribe_kb(lang, settings.main_channel_link),
    )
