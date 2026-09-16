from aiogram import F, Router
from aiogram.filters import Command, CommandObject
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
from bot.locales import t
from bot.services.broadcast import broadcast_copy, broadcast_texts, copy_to_one

router = Router(name="admin")
router.message.filter(F.from_user.id.in_(get_settings().admin_id_list))
router.callback_query.filter(F.from_user.id.in_(get_settings().admin_id_list))


class AdminStates(StatesGroup):
    broadcast_content = State()
    broadcast_confirm = State()
    direct_content = State()


def confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📤 Отправить", callback_data="bc_go"),
                InlineKeyboardButton(text="❌ Отменить", callback_data="bc_cancel"),
            ]
        ]
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.")


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    await message.answer(
        "Админ-команды:\n"
        "/users — зарегистрированные пользователи, их заявки и файлы "
        "(поиск: /users Иванов, /users @username или /users 901234567)\n"
        "/new_project — создать проект\n"
        "/projects — проекты: редактирование, заявки, выгрузка\n"
        "/new_contest — создать конкурс\n"
        "/contests — конкурсы: итоги, редактирование, выгрузка\n"
        "/broadcast — рассылка всем пользователям\n"
        "/message <tg_id, @username или телефон> — сообщение пользователю\n"
        "/ask_profile — напомнить дополнить профиль тем, кто не указал новые данные\n"
        "/stats — статистика\n"
        "/cancel — отменить текущую операцию"
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message, session: AsyncSession) -> None:
    total, subscribed, complete = await repo.stats(session)
    await message.answer(
        f"👥 Зарегистрировано: {total}\n"
        f"📢 Подтвердили подписку: {subscribed}\n"
        f"📝 Заполнили профиль (дата рождения, учёба/работа): {complete}"
    )


@router.message(Command("ask_profile"))
async def cmd_ask_profile(message: Message, session: AsyncSession) -> None:
    users = await repo.users_with_incomplete_profile(session)
    if not users:
        await message.answer("Все пользователи уже заполнили профиль ✅")
        return
    await message.answer(f"Отправляю напоминание {len(users)} пользователям…")
    sent, failed = await broadcast_texts(
        message.bot, {u.tg_id: t(u.language, "profile_reminder") for u in users}
    )
    await message.answer(f"Готово. Доставлено: {sent}, не доставлено: {failed}.")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminStates.broadcast_content)
    await message.answer(
        "Пришлите сообщение для рассылки (текст, фото/видео/документ с подписью). /cancel — отмена."
    )


@router.message(AdminStates.broadcast_content)
async def broadcast_content(message: Message, state: FSMContext) -> None:
    await state.update_data(from_chat_id=message.chat.id, message_id=message.message_id)
    await state.set_state(AdminStates.broadcast_confirm)
    await message.answer("Превью рассылки ⬇️")
    await message.bot.copy_message(message.chat.id, message.chat.id, message.message_id)
    await message.answer("Отправить всем пользователям?", reply_markup=confirm_kb())


@router.callback_query(AdminStates.broadcast_confirm, F.data == "bc_cancel")
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text("Рассылка отменена.")


@router.callback_query(AdminStates.broadcast_confirm, F.data == "bc_go")
async def broadcast_go(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    await state.clear()
    await callback.answer()
    await callback.message.edit_text("Рассылка запущена…")
    chat_ids = await repo.all_user_ids(session)
    sent, failed = await broadcast_copy(
        callback.bot, chat_ids, data["from_chat_id"], data["message_id"]
    )
    await callback.message.answer(
        f"Готово. Доставлено: {sent}, не доставлено (бот заблокирован и т.п.): {failed}."
    )


@router.message(Command("message"))
async def cmd_message(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if not command.args:
        await message.answer("Использование: /message <tg_id, @username или телефон>")
        return
    arg = command.args.strip()
    target = None
    if arg.startswith("@"):
        target = await repo.get_user_by_username(session, arg)
    elif arg.lstrip("+").isdigit() and not arg.startswith("+"):
        target = await repo.get_user(session, int(arg))
    if target is None and not arg.startswith("@"):
        target = await repo.get_user_by_phone(session, arg)
    if target is None:
        await message.answer("Пользователь не найден (ни по ID, ни по username, ни по телефону).")
        return
    await state.set_state(AdminStates.direct_content)
    await state.update_data(target_tg_id=target.tg_id)
    await message.answer(
        f"Получатель: {target.display_name}, {target.phone}.\n"
        "Пришлите сообщение — я отправлю его этому пользователю. /cancel — отмена."
    )


@router.message(AdminStates.direct_content)
async def direct_content(
    message: Message, state: FSMContext
) -> None:
    data = await state.get_data()
    await state.clear()
    ok = await copy_to_one(
        message.bot, data["target_tg_id"], message.chat.id, message.message_id
    )
    await message.answer("Отправлено ✅" if ok else "Не удалось отправить (пользователь заблокировал бота?).")
