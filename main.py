"""Entrypoint for the personal finance Telegram bot."""

from __future__ import annotations

import logging
from typing import Sequence

from telegram import BotCommand
from telegram.ext import Application

from finbot.config import load_messages, load_settings, setup_logging
from finbot.handlers import register_handlers
from finbot.storage import UserStorage

LOGGER = logging.getLogger(__name__)


async def _post_init(application: Application) -> None:
    """Set bot commands in Telegram menu."""
    commands: Sequence[BotCommand] = [
        BotCommand("start", "Начать сбор финансовых данных"),
        BotCommand("help", "Показать справку по боту"),
        BotCommand("plan", "Показать последний финансовый план"),
        BotCommand("reset", "Удалить мои сохраненные данные"),
    ]
    await application.bot.set_my_commands(commands)


def main() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)

    messages = load_messages(settings.config_path)
    storage = UserStorage(settings.database_path)

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .build()
    )
    application.bot_data["storage"] = storage
    application.bot_data["messages"] = messages

    register_handlers(application)
    LOGGER.info("Finance bot started")
    application.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
