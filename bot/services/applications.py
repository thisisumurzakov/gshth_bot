import csv
import io
import logging
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile

from bot.config import Settings
from bot.db.models import Project, ProjectApplication, User
from bot.services.timeutil import format_date, format_local_datetime

logger = logging.getLogger(__name__)

MESSAGE_LIMIT = 4096


def user_summary_html(user: User) -> str:
    lines = [
        f'👤 <a href="tg://user?id={user.tg_id}">{escape(user.full_name)}</a>'
        + (f" @{escape(user.username)}" if user.username else "")
        + f" (ID {user.tg_id})",
        f"📱 {escape(user.phone)}",
    ]
    if user.birth_date:
        lines.append(f"🎂 {format_date(user.birth_date)}")
    if user.workplace:
        lines.append(f"🏢 {escape(user.workplace)}")
    return "\n".join(lines)


async def notify_new_application(
    bot: Bot,
    settings: Settings,
    project: Project,
    application: ProjectApplication,
    user: User,
) -> None:
    """Пересылает заявку в чат заявок (или админам). Файлы уходят по file_id —
    бот их не скачивает."""
    header = (
        f"📝 Новая заявка на проект «{escape(project.title)}»\n\n"
        + user_summary_html(user)
    )
    letter = (
        f"\n\n✉️ Мотивационное письмо:\n{escape(application.letter_text)}"
        if application.letter_text
        else ""
    )
    chat_ids = (
        [settings.applications_chat_id]
        if settings.applications_chat_id
        else settings.admin_id_list
    )
    for chat_id in chat_ids:
        try:
            if len(header + letter) <= MESSAGE_LIMIT:
                await bot.send_message(chat_id, header + letter, parse_mode="HTML")
            else:
                await bot.send_message(chat_id, header, parse_mode="HTML")
                await bot.send_message(
                    chat_id, application.letter_text[:MESSAGE_LIMIT]
                )
            if application.cv_file_id:
                await bot.send_document(
                    chat_id, application.cv_file_id, caption=f"CV — {user.display_name}"
                )
            if application.letter_file_id:
                await bot.send_document(
                    chat_id,
                    application.letter_file_id,
                    caption=f"Мотивационное письмо — {user.display_name}",
                )
        except TelegramAPIError:
            logger.exception("Не удалось отправить заявку в чат %s", chat_id)


def _csv_file(filename: str, header: list[str], rows: list[list]) -> BufferedInputFile:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    # utf-8-sig — чтобы Excel правильно открыл кириллицу. Файл собирается в памяти.
    return BufferedInputFile(buffer.getvalue().encode("utf-8-sig"), filename=filename)


def _user_columns(user: User) -> list:
    return [
        user.tg_id,
        user.full_name,
        f"@{user.username}" if user.username else "",
        user.phone,
        format_date(user.birth_date) if user.birth_date else "",
        user.workplace or "",
    ]


USER_HEADER = ["tg_id", "Имя", "Username", "Телефон", "Дата рождения", "Место учёбы/работы"]


def users_csv(users: list[User]) -> BufferedInputFile:
    return _csv_file(
        "users.csv",
        USER_HEADER + ["Язык", "Подписка подтверждена", "Регистрация"],
        [
            _user_columns(user)
            + [
                user.language,
                format_local_datetime(user.subscribed_at) if user.subscribed_at else "",
                format_local_datetime(user.created_at),
            ]
            for user in users
        ],
    )


def applications_csv(
    project: Project, rows: list[tuple[ProjectApplication, User]]
) -> BufferedInputFile:
    return _csv_file(
        f"project_{project.id}_applications.csv",
        USER_HEADER + ["Дата заявки", "CV", "Мотивационное письмо"],
        [
            _user_columns(user)
            + [
                format_local_datetime(app.created_at),
                "да" if app.cv_file_id else "",
                app.letter_text or ("файл" if app.letter_file_id else ""),
            ]
            for app, user in rows
        ],
    )


def contest_csv(contest_id: int, ranking: list[tuple[User, int]]) -> BufferedInputFile:
    return _csv_file(
        f"contest_{contest_id}_results.csv",
        ["Место"] + USER_HEADER + ["Приглашено"],
        [
            [place] + _user_columns(user) + [count]
            for place, (user, count) in enumerate(ranking, start=1)
        ],
    )
