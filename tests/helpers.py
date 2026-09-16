"""Каркас для тестов: Dispatcher бота с подменённым Telegram API."""

from datetime import datetime, timezone
from itertools import count

from aiogram import Bot, methods
from aiogram.client.session.base import BaseSession
from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatInviteLink,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberUpdated,
    Message,
    Update,
    User as TgUser,
)

from bot.main import build_dispatcher

ADMIN_ID = 999
CHANNEL_ID = -100777


class FakeSession(BaseSession):
    """Записывает вызовы Bot API и возвращает правдоподобные ответы."""

    def __init__(self):
        super().__init__()
        self.calls: list[methods.TelegramMethod] = []
        self._ids = count(1000)

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (methods.SendMessage, methods.SendPhoto, methods.SendDocument)):
            return Message(
                message_id=next(self._ids),
                date=datetime.now(timezone.utc),
                chat=Chat(id=method.chat_id, type="private"),
                text=getattr(method, "text", None),
            )
        if isinstance(method, methods.GetChatMember):
            return ChatMemberMember(user=TgUser(id=method.user_id, is_bot=False, first_name="U"))
        if isinstance(method, methods.CreateChatInviteLink):
            return ChatInviteLink(
                invite_link=f"https://t.me/+link{next(self._ids)}",
                creator=TgUser(id=42, is_bot=True, first_name="Bot"),
                creates_join_request=False,
                is_primary=False,
                is_revoked=False,
            )
        return True

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        yield b""

    def pop(self) -> list[methods.TelegramMethod]:
        calls, self.calls = self.calls, []
        return calls


class Harness:
    def __init__(self, session_factory):
        self.api = FakeSession()
        self.bot = Bot("42:TEST", session=self.api)
        self.dp = build_dispatcher(session_factory)
        self._update_ids = count(1)
        self._message_ids = count(1)

    def _user(self, tg_id):
        return TgUser(id=tg_id, is_bot=False, first_name="Test")

    def _message(self, tg_id, **fields):
        return Message(
            message_id=next(self._message_ids),
            date=datetime.now(timezone.utc),
            chat=Chat(id=tg_id, type="private"),
            from_user=self._user(tg_id),
            **fields,
        )

    async def feed(self, **event):
        update = Update(update_id=next(self._update_ids), **event)
        await self.dp.feed_update(self.bot, update)
        return self.api.pop()

    async def send(self, tg_id, text=None, **fields):
        return await self.feed(message=self._message(tg_id, text=text, **fields))

    async def press(self, tg_id, data):
        callback = CallbackQuery(
            id=str(next(self._update_ids)),
            from_user=self._user(tg_id),
            chat_instance="ci",
            data=data,
            message=self._message(tg_id, text="old"),
        )
        return await self.feed(callback_query=callback)

    async def channel_event(self, tg_id, joined: bool, link: str | None):
        user = self._user(tg_id)
        old = ChatMemberLeft(user=user) if joined else ChatMemberMember(user=user)
        new = ChatMemberMember(user=user) if joined else ChatMemberLeft(user=user)
        invite = (
            ChatInviteLink(
                invite_link=link,
                creator=TgUser(id=42, is_bot=True, first_name="Bot"),
                creates_join_request=False,
                is_primary=False,
                is_revoked=False,
            )
            if link
            else None
        )
        event = ChatMemberUpdated(
            chat=Chat(id=CHANNEL_ID, type="channel", title="Contest channel"),
            from_user=user,
            date=datetime.now(timezone.utc),
            old_chat_member=old,
            new_chat_member=new,
            invite_link=invite,
        )
        return await self.feed(chat_member=event)


def sent_texts(calls) -> str:
    parts = []
    for call in calls:
        if isinstance(call, methods.SendMessage):
            parts.append(call.text)
        elif isinstance(call, (methods.SendPhoto, methods.SendDocument)):
            parts.append(call.caption or "")
        elif isinstance(call, methods.AnswerCallbackQuery):
            parts.append(call.text or "")
    return "\n".join(parts)
