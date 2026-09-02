# aki-bot — реферальный бот Global Shapers Tashkent Hub

Telegram-бот: регистрация (имя, телефон, язык uz/ru/en), проверка подписки на
канал GShTH, персональная пригласительная ссылка каждому пользователю и доступ
в закрытый канал после 3 приглашённых. Спецификация и план — в
`docs/superpowers/`.

## Подготовка

1. Создайте бота у [@BotFather](https://t.me/BotFather), получите токен.
2. Добавьте бота **администратором** в оба канала (GShTH и закрытый) с правом
   «Приглашать пользователей» («Invite users via link»).
3. Узнайте ID каналов (например, переслав пост из канала боту
   [@getidsbot](https://t.me/getidsbot); ID канала начинается с `-100`).

## Запуск локально

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # затем заполните значения
.venv/bin/python -m bot.main
```

База SQLite создаётся автоматически в `data/bot.db` (путь настраивается через
`DB_PATH`).

## Тесты

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

## Запуск в Docker

```bash
cp .env.example .env   # заполнить значения
docker compose up -d --build
```

База хранится на хосте в `./data/bot.db` (примонтированный том), поэтому
пересборка и перезапуск контейнера данные не трогают. Логи:
`docker compose logs -f`.

## Деплой на VPS (systemd, без Docker)

```bash
sudo useradd -r -m -d /opt/aki-bot akibot
sudo -u akibot git clone <repo> /opt/aki-bot
cd /opt/aki-bot && sudo -u akibot python3 -m venv .venv && sudo -u akibot .venv/bin/pip install -r requirements.txt
sudo -u akibot cp .env.example .env   # заполнить значения
sudo cp deploy/aki-bot.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now aki-bot
```

Логи: `journalctl -u aki-bot -f`. Бэкап базы — копия файла `data/bot.db`.

## Миграции схемы (Alembic)

Схема создаётся автоматически при первом запуске. При изменении моделей в
будущем:

```bash
.venv/bin/alembic revision --autogenerate -m "описание"
.venv/bin/alembic upgrade head
```

(на уже работающей базе перед первой миграцией один раз выполните
`.venv/bin/alembic stamp head`).

## Админ-команды (в личке с ботом, для ID из `ADMIN_IDS`)

- `/broadcast` — рассылка всем пользователям (любой тип сообщения, превью и
  подтверждение перед отправкой);
- `/message <tg_id или телефон>` — сообщение конкретному пользователю;
- `/stats` — статистика;
- `/cancel` — отменить текущую админ-операцию.
