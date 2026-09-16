import asyncio
from collections.abc import Awaitable, Callable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

SEND_INTERVAL = 0.05  # ~20 сообщений/сек — лимит Telegram на рассылки


async def _send_with_retry(send: Callable[[], Awaitable[object]]) -> bool:
    try:
        await send()
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            await send()
            return True
        except TelegramAPIError:
            return False
    except TelegramAPIError:
        return False


async def copy_to_one(bot: Bot, chat_id: int, from_chat_id: int, message_id: int) -> bool:
    return await _send_with_retry(
        lambda: bot.copy_message(chat_id, from_chat_id, message_id)
    )


async def broadcast_copy(
    bot: Bot, chat_ids: list[int], from_chat_id: int, message_id: int
) -> tuple[int, int]:
    """Копирует сообщение всем chat_ids. Возвращает (доставлено, не доставлено)."""
    sent = failed = 0
    for chat_id in chat_ids:
        if await copy_to_one(bot, chat_id, from_chat_id, message_id):
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(SEND_INTERVAL)
    return sent, failed


async def broadcast_texts(bot: Bot, texts: dict[int, str]) -> tuple[int, int]:
    """Отправляет каждому chat_id свой текст (например, на его языке)."""
    sent = failed = 0
    for chat_id, text in texts.items():
        if await _send_with_retry(lambda: bot.send_message(chat_id, text)):
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(SEND_INTERVAL)
    return sent, failed
