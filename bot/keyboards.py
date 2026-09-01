from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from bot.locales import t

LANGUAGE_LABELS = {"uz": "O'zbekcha 🇺🇿", "ru": "Русский 🇷🇺", "en": "English 🇬🇧"}


def language_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"setlang:{code}")]
            for code, label in LANGUAGE_LABELS.items()
        ]
    )


def contact_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "btn_share_contact"), request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def subscribe_kb(lang: str, channel_link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "btn_open_channel"), url=channel_link)],
            [InlineKeyboardButton(text=t(lang, "btn_i_subscribed"), callback_data="check_sub")],
        ]
    )


def menu_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "btn_change_language"), callback_data="change_lang")]
        ]
    )
