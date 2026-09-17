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


async def _send_application(
    bot: Bot,
    chat_id: int,
    project: Project,
    application: ProjectApplication,
    user: User,
) -> str | None:
    """Отправляет заявку в один чат. Части уходят независимо: если Telegram отклонит,
    например, документ, текст и остальные файлы всё равно дойдут.
    Возвращает текст первой ошибки или None."""
    header = (
        f"📝 Новая заявка на проект «{escape(project.title)}»\n\n"
        + user_summary_html(user)
    )
    letter = (
        f"\n\n✉️ Мотивационное письмо:\n{escape(application.letter_text)}"
        if application.letter_text
        else ""
    )
    if len(header + letter) <= MESSAGE_LIMIT:
        parts = [lambda: bot.send_message(chat_id, header + letter, parse_mode="HTML")]
    else:
        parts = [
            lambda: bot.send_message(chat_id, header, parse_mode="HTML"),
            lambda: bot.send_message(chat_id, application.letter_text[:MESSAGE_LIMIT]),
        ]
    if application.cv_file_id:
        parts.append(
            lambda: bot.send_document(
                chat_id, application.cv_file_id, caption=f"CV — {user.display_name}"
            )
        )
    if application.letter_file_id:
        parts.append(
            lambda: bot.send_document(
                chat_id,
                application.letter_file_id,
                caption=f"Мотивационное письмо — {user.display_name}",
            )
        )

    first_error = None
    for send in parts:
        try:
            await send()
        except TelegramAPIError as e:
            logger.warning("Заявка не доставлена в чат %s: %s", chat_id, e.message)
            first_error = first_error or e.message
    return first_error


async def notify_new_application(
    bot: Bot,
    settings: Settings,
    project: Project,
    application: ProjectApplication,
    user: User,
) -> None:
    """Пересылает заявку в чат заявок, а если не задан или не получилось — админам.
    Файлы уходят по file_id: бот их не скачивает."""
    chat_id = settings.applications_chat_id
    if chat_id:
        error = await _send_application(bot, chat_id, project, application, user)
        if error is None:
            return
        warning = (
            f"⚠️ Заявка не полностью доставлена в чат заявок ({chat_id}).\n"
            f"Ответ Telegram: {error}\n"
            "Проверьте права бота командой /check_chat. Полная заявка — ниже."
        )
    else:
        warning = None
    for admin_id in settings.admin_id_list:
        try:
            if warning:
                await bot.send_message(admin_id, warning)
        except TelegramAPIError:
            logger.warning("Не удалось предупредить админа %s", admin_id)
        await _send_application(bot, admin_id, project, application, user)


def _csv_file(filename: str, header: list[str], rows: list[list]) -> BufferedInputFile:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    # utf-8-sig — чтобы Excel правильно открыл кириллицу. Файл собирается в памяти.
    return BufferedInputFile(buffer.getvalue().encode("utf-8-sig"), filename=filename)


def file_link(bot_username: str, kind: str, application: ProjectApplication) -> str:
    """Ссылка на CV или письмо для таблиц. Прямой ссылки на файл Telegram нет без
    токена бота, поэтому это deep link: у админа бот по ней присылает файл, а для
    остальных она просто открывает бота."""
    return (
        f"https://t.me/{bot_username}?start="
        f"{kind}_{application.project_id}_{application.tg_id}"
    )


def _file_links(bot_username: str, app: ProjectApplication) -> list[str]:
    return [
        file_link(bot_username, "cv", app) if app.cv_file_id else "",
        file_link(bot_username, "letter", app)
        if app.letter_file_id or app.letter_text
        else "",
    ]


def _user_columns(user: User) -> list:
    return [
        user.tg_id,
        user.full_name,
        # Без «@»: Excel принимает ячейку, начинающуюся с @, за формулу.
        user.username or "",
        user.phone,
        format_date(user.birth_date) if user.birth_date else "",
        user.workplace or "",
    ]


USER_HEADER = ["tg_id", "Имя", "Username", "Телефон", "Дата рождения", "Место учёбы/работы"]


def users_csv(
    users: list[User],
    applications: dict[int, list[tuple[ProjectApplication, Project]]],
    bot_username: str,
) -> BufferedInputFile:
    rows = []
    for user in users:
        user_apps = applications.get(user.tg_id, [])
        links = [_file_links(bot_username, app) for app, _ in user_apps]
        rows.append(
            _user_columns(user)
            + [
                user.language,
                format_local_datetime(user.subscribed_at) if user.subscribed_at else "",
                format_local_datetime(user.created_at),
                # По строке на заявку — в том же порядке во всех трёх колонках.
                "\n".join(project.title for _, project in user_apps),
                "\n".join(cv for cv, _ in links),
                "\n".join(letter for _, letter in links),
            ]
        )
    return _csv_file(
        "users.csv",
        USER_HEADER
        + [
            "Язык",
            "Подписка подтверждена",
            "Регистрация",
            "Заявки на проекты",
            "CV",
            "Мотивационное письмо",
        ],
        rows,
    )


def applications_csv(
    project: Project,
    rows: list[tuple[ProjectApplication, User]],
    bot_username: str,
) -> BufferedInputFile:
    return _csv_file(
        f"project_{project.id}_applications.csv",
        USER_HEADER + ["Дата заявки", "CV", "Мотивационное письмо", "Текст письма"],
        [
            _user_columns(user)
            + [format_local_datetime(app.created_at)]
            + _file_links(bot_username, app)
            + [app.letter_text or ""]
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
