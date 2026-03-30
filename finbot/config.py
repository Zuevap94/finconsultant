"""Configuration loading utilities for the finance bot."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    telegram_bot_token: str
    database_path: str
    config_path: str
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    log_level: str = "INFO"


def load_settings() -> Settings:
    """Load runtime settings from .env and environment variables."""
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    db_path = os.getenv("DATABASE_PATH", "data/finbot.sqlite3").strip()
    config_path = os.getenv("CONFIG_PATH", "config/messages.json").strip()
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    if not token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN is not set. Please create .env from .env.example."
        )

    return Settings(
        telegram_bot_token=token,
        database_path=db_path,
        config_path=config_path,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        log_level=log_level,
    )


def setup_logging(level: str) -> None:
    """Configure app-wide logging."""
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )


def load_messages(config_path: str) -> Dict[str, Any]:
    """Load response templates from JSON config."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
