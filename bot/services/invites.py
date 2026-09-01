from aiogram import Bot


async def create_personal_link(bot: Bot, channel_id: int, tg_id: int) -> str:
    """Персональная ссылка пользователя в канал GShTH: по ней считаем рефералов."""
    link = await bot.create_chat_invite_link(channel_id, name=f"ref {tg_id}")
    return link.invite_link


async def create_private_link(bot: Bot, channel_id: int, tg_id: int) -> str:
    """Одноразовая ссылка в закрытый канал: member_limit=1, передать её нельзя."""
    link = await bot.create_chat_invite_link(
        channel_id, name=f"private {tg_id}", member_limit=1
    )
    return link.invite_link
