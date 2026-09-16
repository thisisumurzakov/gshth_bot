import re
from datetime import date

from aiogram import Bot, F, Router
from aiogram.filters import Filter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from bot import keyboards
from bot.db import repo
from bot.db.models import User
from bot.handlers.flows import send_language_prompt, send_next_step
from bot.locales import LANGS, t
from bot.services.timeutil import TASHKENT, parse_birth_date

router = Router(name="registration")

PHONE_RE = re.compile(r"^\+?\d{9,15}$")
WORKPLACE_MAX_LEN = 200

# Текстовый ответ, но не команда: /start посреди анкеты должен срабатывать как /start.
PLAIN_TEXT = F.text & ~F.text.startswith("/")


class Registration(StatesGroup):
    full_name = State()
    phone = State()
    birth_date = State()
    workplace = State()


class IncompleteProfile(Filter):
    """Пользователь зарегистрирован, но не указал дату рождения или место учёбы/работы."""

    async def __call__(self, event: TelegramObject, user: User | None = None) -> bool:
        return user is not None and not user.profile_complete


async def ask_profile(bot: Bot, user: User, state: FSMContext) -> None:
    await state.set_state(Registration.birth_date)
    await state.set_data({"language": user.language})
    text = t(user.language, "profile_update_intro") + "\n\n" + t(user.language, "ask_birth_date")
    await bot.send_message(user.tg_id, text, reply_markup=ReplyKeyboardRemove())


# --- Недозаполненный профиль (в т.ч. пользователи, зарегистрированные до появления
# этих полей): любое обращение к боту сначала ведёт в анкету. ---


@router.message(IncompleteProfile(), ~StateFilter(Registration))
async def gate_message(message: Message, state: FSMContext, user: User) -> None:
    await ask_profile(message.bot, user, state)


@router.callback_query(IncompleteProfile(), ~StateFilter(Registration))
async def gate_callback(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await ask_profile(callback.bot, user, state)


# --- Регистрация ---


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
        # Смена языка уже зарегистрированным пользователем.
        user.language = lang
        await session.commit()
        await send_next_step(callback.bot, user, prefix=t(lang, "language_changed"))
        return
    await state.update_data(language=lang)
    await state.set_state(Registration.full_name)
    await callback.message.answer(t(lang, "ask_full_name"))


@router.message(Registration.full_name, PLAIN_TEXT)
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


@router.message(Registration.phone, F.contact | PLAIN_TEXT)
async def process_phone(
    message: Message, state: FSMContext, session: AsyncSession, user: User | None
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

    if user is None:
        await repo.create_user(
            session,
            tg_id=message.from_user.id,
            full_name=data["full_name"],
            phone=phone,
            language=lang,
        )
    await state.set_state(Registration.birth_date)
    await message.answer(t(lang, "ask_birth_date"), reply_markup=ReplyKeyboardRemove())


@router.message(Registration.birth_date, PLAIN_TEXT)
async def process_birth_date(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data["language"]
    birth_date = parse_birth_date(message.text, today=message.date.astimezone(TASHKENT).date())
    if birth_date is None:
        await message.answer(t(lang, "birth_date_invalid"))
        return
    await state.update_data(birth_date=birth_date.isoformat())
    await state.set_state(Registration.workplace)
    await message.answer(t(lang, "ask_workplace"))


@router.message(Registration.workplace, PLAIN_TEXT)
async def process_workplace(
    message: Message, state: FSMContext, session: AsyncSession, user: User | None
) -> None:
    data = await state.get_data()
    lang = data["language"]
    workplace = " ".join(message.text.split())
    if len(workplace) < 2 or len(workplace) > WORKPLACE_MAX_LEN:
        await message.answer(t(lang, "workplace_invalid"))
        return
    await state.clear()
    if user is None:
        # Запись пропала (например, база очищена) — начинаем заново.
        await send_language_prompt(message.bot, message.chat.id)
        return

    await repo.update_profile(
        session, user, date.fromisoformat(data["birth_date"]), workplace
    )
    # Ещё не дошёл до подписки — для него это конец регистрации, а не обновление данных.
    done_key = "registered" if user.subscribed_at is None else "profile_saved"
    await send_next_step(message.bot, user, prefix=t(user.language, done_key))


@router.message(StateFilter(Registration), ~F.text.startswith("/"))
async def process_unexpected(message: Message, state: FSMContext) -> None:
    """Стикер, фото и т.п. вместо ответа на вопрос анкеты — повторяем вопрос."""
    data = await state.get_data()
    lang = data.get("language")
    current = await state.get_state()
    question = {
        Registration.full_name.state: "ask_full_name",
        Registration.phone.state: "ask_phone",
        Registration.birth_date.state: "ask_birth_date",
        Registration.workplace.state: "ask_workplace",
    }[current]
    await message.answer(t(lang, question))
