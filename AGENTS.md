# AGENTS.md

## Cursor Cloud specific instructions

This is a **FinConsultant Telegram Bot** — a single-process Python application (no Docker, no external services beyond Telegram API). See `README.md` for full feature description.

### Running the bot

```bash
source .venv/bin/activate
python main.py
```

The bot requires a valid `TELEGRAM_BOT_TOKEN` in `.env` (copy from `.env.example`). Without a valid token the bot starts but immediately errors with `telegram.error.InvalidToken`. All other config values have sane defaults.

### Key architecture notes

- **19-state ConversationHandler FSM** in `finbot/handlers.py` — the bot collects financial data step-by-step.
- **Pure-Python financial engine** in `finbot/finance.py` — all calculations are local, no external API calls.
- **SQLite** via stdlib `sqlite3` — auto-created at `data/finbot.sqlite3`; no separate DB process needed.
- **No automated tests exist** in the repo. To validate logic, run the finance engine directly (see verification script pattern in PR history).
- **No linter/formatter config** exists (no `pyproject.toml`, `setup.cfg`, `ruff.toml`, etc.).

### Caveats

- `python3.12-venv` apt package is required to create the virtualenv (not installed by default in the base VM image).
- The `.env` file is gitignored. Each agent session must ensure `.env` exists (the update script handles this).
