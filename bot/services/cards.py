"""Карточки проектов и конкурсов: HTML-текст + необязательное фото по file_id."""

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InaccessibleMessage, InlineKeyboardMarkup, Message

CAPTION_LIMIT = 1024


def extract_content(message: Message) -> tuple[str, str | None] | None:
    """Описание из сообщения админа: (HTML-текст, file_id фото) или None."""
    if message.photo:
        if not message.caption:
            return None
        return message.html_text, message.photo[-1].file_id
    if message.text:
        return message.html_text, None
    return None


async def send_card(
    bot: Bot,
    chat_id: int,
    text: str,
    photo_file_id: str | None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if photo_file_id is None:
        await bot.send_message(
            chat_id, text, parse_mode="HTML", reply_markup=reply_markup
        )
    elif len(text) <= CAPTION_LIMIT:
        await bot.send_photo(
            chat_id,
            photo_file_id,
            caption=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    else:
        # Подпись к фото ограничена 1024 символами — длинный текст отдельным сообщением.
        await bot.send_photo(chat_id, photo_file_id)
        await bot.send_message(
            chat_id, text, parse_mode="HTML", reply_markup=reply_markup
        )


async def delete_quietly(message: Message | InaccessibleMessage | None) -> None:
    """Удаляет сообщение с кнопками перед показом следующего экрана.

    Проще, чем редактировать: экраны бывают то с фото, то без.
    """
    if not isinstance(message, Message):
        return
    try:
        await message.delete()
    except TelegramBadRequest:
        pass  # старше 48 часов или уже удалено
