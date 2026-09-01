from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from bot.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    full_name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(32))
    language: Mapped[str] = mapped_column(String(5), default="ru")
    invite_link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    private_invite_link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Referral(Base):
    __tablename__ = "referrals"

    joined_tg_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False
    )
    inviter_tg_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id"), index=True
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
