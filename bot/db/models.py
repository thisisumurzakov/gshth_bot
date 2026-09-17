from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.orm import Mapped, mapped_column

from bot.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """SQLite не хранит часовой пояс: пишем naive UTC, читаем обратно как aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class User(Base):
    __tablename__ = "users"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    full_name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(32))
    # Username из Telegram, обновляется при каждом обращении к боту.
    # "" — username нет; NULL — ещё не проверяли (старые записи, см. backfill_usernames).
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language: Mapped[str] = mapped_column(String(5), default="ru")
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    workplace: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subscribed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    @property
    def display_name(self) -> str:
        """«Имя (@username)» — для админских списков и уведомлений."""
        return f"{self.full_name} (@{self.username})" if self.username else self.full_name

    @property
    def profile_complete(self) -> bool:
        return self.birth_date is not None and self.workplace is not None


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(64))
    # HTML-разметка описания (текст или подпись к фото).
    description: Mapped[str] = mapped_column(Text)
    # Храним только file_id — само фото остаётся на серверах Telegram.
    photo_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    require_cv: Mapped[bool] = mapped_column(Boolean, default=False)
    require_letter: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ProjectApplication(Base):
    __tablename__ = "project_applications"

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    tg_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id"), primary_key=True
    )
    cv_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    letter_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    letter_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Contest(Base):
    __tablename__ = "contests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    photo_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    channel_title: Mapped[str] = mapped_column(String(255))
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ContestParticipant(Base):
    __tablename__ = "contest_participants"

    contest_id: Mapped[int] = mapped_column(ForeignKey("contests.id"), primary_key=True)
    tg_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id"), primary_key=True
    )
    invite_link: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ContestJoin(Base):
    __tablename__ = "contest_joins"

    # Один человек засчитывается в конкурсе только один раз и только одному пригласившему.
    contest_id: Mapped[int] = mapped_column(ForeignKey("contests.id"), primary_key=True)
    joined_tg_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False
    )
    inviter_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # Вышедшие из канала до окончания конкурса не засчитываются.
    left_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
