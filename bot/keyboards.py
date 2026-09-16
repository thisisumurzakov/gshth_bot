from urllib.parse import quote

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from bot.db.models import Contest, Project
from bot.locales import t

LANGUAGE_LABELS = {"uz": "O'zbekcha 🇺🇿", "ru": "Русский 🇷🇺", "en": "English 🇬🇧"}


def language_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"setlang:{code}")]
            for code, label in LANGUAGE_LABELS.items()
        ]
    )


def change_language_inline_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "btn_change_language"), callback_data="change_lang")]
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


def main_menu_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=t(lang, "btn_projects")),
                KeyboardButton(text=t(lang, "btn_contests")),
            ],
            [KeyboardButton(text=t(lang, "btn_change_language"))],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def _button(text: str, data: str) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=text, callback_data=data)]


# --- Проекты ---


def projects_kb(projects: list[Project]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[_button(p.title, f"prj:{p.id}") for p in projects]
    )


def project_kb(lang: str, project_id: int, applied: bool) -> InlineKeyboardMarkup:
    first = (
        _button(t(lang, "btn_applied"), "prj_applied")
        if applied
        else _button(t(lang, "btn_apply"), f"prj_apply:{project_id}")
    )
    return InlineKeyboardMarkup(inline_keyboard=[first, _button(t(lang, "btn_back"), "prj")])


def cancel_application_kb(lang: str, project_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[_button(t(lang, "btn_cancel"), f"prj_cancel:{project_id}")]
    )


# --- Конкурсы ---


def contests_kb(contests: list[Contest]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[_button(c.title, f"cst:{c.id}") for c in contests]
    )


def contest_kb(lang: str, contest_id: int, link: str | None) -> InlineKeyboardMarkup:
    if link is None:
        rows = [_button(t(lang, "btn_get_link"), f"cst_link:{contest_id}")]
    else:
        share_url = f"https://t.me/share/url?url={quote(link, safe='')}"
        rows = [[InlineKeyboardButton(text=t(lang, "btn_share"), url=share_url)]]
    rows.append(_button(t(lang, "btn_back"), "cst"))
    return InlineKeyboardMarkup(inline_keyboard=rows)
