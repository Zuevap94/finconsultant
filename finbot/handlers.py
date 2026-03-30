"""Telegram handlers and conversation flow."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from finbot.finance import DISCLAIMER, build_plan_message
from finbot.storage import UserStorage
from finbot.validators import parse_non_negative_money, parse_positive_int

LOGGER = logging.getLogger(__name__)

ALLOWED_GOAL_HINTS = (
    "покупка жилья, финансовая подушка, образование детей, пенсия, капитал на бизнес"
)

DEFAULT_MESSAGES = {
    "disclaimer": DISCLAIMER,
    "start_welcome": (
        "Привет! Я помогу собрать данные и подготовить личный финансовый план.\n"
        "Начнем с возраста. Введите число (например, 30)."
    ),
    "help_text": (
        "Команды:\n"
        "/start — начать сбор данных\n"
        "/plan — показать план по сохраненным данным\n"
        "/reset — удалить сохраненные данные\n"
        "/help — справка\n\n"
        "Я отвечаю только на темы финансового планирования. {disclaimer}"
    ),
    "reset_done": "Ваши данные очищены. Для нового расчета используйте /start.",
    "plan_no_data": "Пока нет сохраненных данных. Нажмите /start, чтобы пройти короткий опрос.",
    "unrelated_refusal": (
        "Я специализируюсь только на финансовом планировании. "
        "Давайте вернемся к личному финансовому плану: используйте /start или /plan."
    ),
    "finance_redirect": (
        "Я лучше всего помогаю через структурированный опрос. "
        "Нажмите /start для нового плана или /plan для уже сохраненных данных."
    ),
    "error_message": "Упс, произошла техническая ошибка. Попробуйте еще раз или используйте /start.",
    "goal_examples": ALLOWED_GOAL_HINTS,
}

# Conversation states
(
    AGE,
    FAMILY_STATUS,
    DEPENDENTS,
    MONTHLY_INCOME,
    MONTHLY_EXPENSES,
    CURRENT_SAVINGS,
    ASSET_REAL_ESTATE,
    ASSET_CARS,
    ASSET_SECURITIES,
    ASSET_CRYPTO,
    DEBT_MORTGAGE,
    DEBT_CONSUMER,
    DEBT_OTHER,
    RISK_PROFILE,
    GOAL_NAME,
    GOAL_TARGET,
    GOAL_HORIZON,
    GOAL_PRIORITY,
    GOAL_ADD_MORE,
) = range(19)

FINANCE_KEYWORDS = (
    "бюджет",
    "доход",
    "расход",
    "кредит",
    "ипотека",
    "инвест",
    "финанс",
    "накоп",
    "актив",
    "долг",
    "пенси",
    "подушка",
)


def _message(context: ContextTypes.DEFAULT_TYPE, key: str) -> str:
    messages = context.application.bot_data.get("messages", {})
    template = str(messages.get(key, DEFAULT_MESSAGES.get(key, "")))
    return template.format(
        disclaimer=messages.get("disclaimer", DEFAULT_MESSAGES["disclaimer"])
    )


def _family_status_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("Холост/Не замужем"), KeyboardButton("Женат/Замужем")], [KeyboardButton("В разводе"), KeyboardButton("Другое")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _risk_profile_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("Консервативный"), KeyboardButton("Умеренный"), KeyboardButton("Агрессивный")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _goal_priority_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("Высокий"), KeyboardButton("Средний"), KeyboardButton("Низкий")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _yes_no_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("Да"), KeyboardButton("Нет")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _sanitize_risk(value: str) -> str:
    mapping = {
        "консервативный": "консервативный",
        "умеренный": "умеренный",
        "агрессивный": "агрессивный",
    }
    return mapping.get(value.strip().lower(), "умеренный")


def _is_finance_related(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in FINANCE_KEYWORDS)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start or restart questionnaire."""
    context.user_data.clear()
    context.user_data["goals"] = []
    await update.message.reply_text(_message(context, "start_welcome"))
    return AGE


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(_message(context, "help_text"))


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage: UserStorage = context.application.bot_data["storage"]
    user_id = update.effective_user.id
    storage.delete_profile(user_id)
    context.user_data.clear()
    await update.message.reply_text(
        _message(context, "reset_done"),
        reply_markup=ReplyKeyboardRemove(),
    )


async def plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage: UserStorage = context.application.bot_data["storage"]
    user_id = update.effective_user.id
    profile = storage.get_profile(user_id)
    if profile is None:
        await update.message.reply_text(_message(context, "plan_no_data"))
        return
    message = build_plan_message(profile)
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)


async def age_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        age = parse_positive_int(update.message.text, min_value=18, max_value=100)
    except Exception:
        await update.message.reply_text("Введите корректный возраст числом от 18 до 100.")
        return AGE
    context.user_data["age"] = age
    await update.message.reply_text(
        "Укажите семейный статус:",
        reply_markup=_family_status_keyboard(),
    )
    return FAMILY_STATUS


async def family_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("Выберите семейный статус кнопкой.")
        return FAMILY_STATUS
    context.user_data["family_status"] = text
    await update.message.reply_text("Сколько у вас иждивенцев? (число, можно 0)")
    return DEPENDENTS


async def dependents_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        dependents = parse_positive_int(update.message.text, min_value=0, max_value=20)
    except Exception:
        await update.message.reply_text("Введите число от 0 до 20.")
        return DEPENDENTS
    context.user_data["dependents"] = dependents
    await update.message.reply_text("Ваш средний доход в месяц (в ₽)? Например: 120000")
    return MONTHLY_INCOME


def _validate_money_step(raw: str) -> Optional[float]:
    try:
        return parse_non_negative_money(raw)
    except Exception:
        return None


async def income_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _validate_money_step(update.message.text)
    if value is None or value == 0:
        await update.message.reply_text("Введите корректную сумму дохода больше 0.")
        return MONTHLY_INCOME
    context.user_data["monthly_income"] = value
    await update.message.reply_text("Основные расходы в месяц (в ₽)? Например: 70000")
    return MONTHLY_EXPENSES


async def expenses_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _validate_money_step(update.message.text)
    if value is None:
        await update.message.reply_text("Введите корректную сумму расходов.")
        return MONTHLY_EXPENSES
    context.user_data["monthly_expenses"] = value
    await update.message.reply_text("Текущие сбережения (в ₽)?")
    return CURRENT_SAVINGS


async def current_savings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _validate_money_step(update.message.text)
    if value is None:
        await update.message.reply_text("Введите корректную сумму сбережений.")
        return CURRENT_SAVINGS
    context.user_data["current_savings"] = value
    await update.message.reply_text("Стоимость вашей недвижимости (в ₽, если нет — 0).")
    return ASSET_REAL_ESTATE


async def asset_real_estate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _validate_money_step(update.message.text)
    if value is None:
        await update.message.reply_text("Введите корректную сумму недвижимости.")
        return ASSET_REAL_ESTATE
    context.user_data["assets_real_estate"] = value
    await update.message.reply_text("Стоимость автомобилей (в ₽, если нет — 0).")
    return ASSET_CARS


async def asset_cars_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _validate_money_step(update.message.text)
    if value is None:
        await update.message.reply_text("Введите корректную сумму по автомобилям.")
        return ASSET_CARS
    context.user_data["assets_cars"] = value
    await update.message.reply_text("Стоимость ценных бумаг (в ₽, если нет — 0).")
    return ASSET_SECURITIES


async def asset_securities_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _validate_money_step(update.message.text)
    if value is None:
        await update.message.reply_text("Введите корректную сумму по ценным бумагам.")
        return ASSET_SECURITIES
    context.user_data["assets_securities"] = value
    await update.message.reply_text("Стоимость криптовалют (в ₽, если нет — 0).")
    return ASSET_CRYPTO


async def asset_crypto_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _validate_money_step(update.message.text)
    if value is None:
        await update.message.reply_text("Введите корректную сумму по криптовалютам.")
        return ASSET_CRYPTO
    context.user_data["assets_crypto"] = value
    await update.message.reply_text("Остаток по ипотеке (в ₽, если нет — 0).")
    return DEBT_MORTGAGE


async def debt_mortgage_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _validate_money_step(update.message.text)
    if value is None:
        await update.message.reply_text("Введите корректную сумму ипотеки.")
        return DEBT_MORTGAGE
    context.user_data["debt_mortgage"] = value
    await update.message.reply_text("Потребительские кредиты (в ₽, если нет — 0).")
    return DEBT_CONSUMER


async def debt_consumer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _validate_money_step(update.message.text)
    if value is None:
        await update.message.reply_text("Введите корректную сумму потребительских кредитов.")
        return DEBT_CONSUMER
    context.user_data["debt_consumer"] = value
    await update.message.reply_text("Прочие долги (в ₽, если нет — 0).")
    return DEBT_OTHER


async def debt_other_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _validate_money_step(update.message.text)
    if value is None:
        await update.message.reply_text("Введите корректную сумму прочих долгов.")
        return DEBT_OTHER
    context.user_data["debt_other"] = value
    await update.message.reply_text(
        "Какой у вас риск-профиль?",
        reply_markup=_risk_profile_keyboard(),
    )
    return RISK_PROFILE


async def risk_profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["risk_profile"] = _sanitize_risk(update.message.text)
    context.user_data["goals"] = []
    await update.message.reply_text(
        "Добавим финансовые цели.\n"
        f"Введите первую цель (например: {_message(context, 'goal_examples')}).",
        reply_markup=ReplyKeyboardRemove(),
    )
    return GOAL_NAME


async def goal_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("Название цели слишком короткое. Введите чуть подробнее.")
        return GOAL_NAME
    context.user_data["current_goal_name"] = name
    await update.message.reply_text("Какую сумму хотите накопить для этой цели (в ₽)?")
    return GOAL_TARGET


async def goal_target_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _validate_money_step(update.message.text)
    if value is None or value == 0:
        await update.message.reply_text("Введите корректную сумму больше 0.")
        return GOAL_TARGET
    context.user_data["current_goal_target"] = value
    await update.message.reply_text("За сколько лет хотите достичь цели? (1-50)")
    return GOAL_HORIZON


async def goal_horizon_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        horizon = parse_positive_int(update.message.text, min_value=1, max_value=50)
    except Exception:
        await update.message.reply_text("Введите число от 1 до 50.")
        return GOAL_HORIZON
    context.user_data["current_goal_horizon"] = horizon
    await update.message.reply_text(
        "Приоритет цели?",
        reply_markup=_goal_priority_keyboard(),
    )
    return GOAL_PRIORITY


async def goal_priority_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    priority_raw = update.message.text.strip().lower()
    allowed = {"высокий", "средний", "низкий"}
    if priority_raw not in allowed:
        await update.message.reply_text("Выберите приоритет кнопкой: Высокий, Средний или Низкий.")
        return GOAL_PRIORITY

    goals: List[Dict[str, Any]] = context.user_data.setdefault("goals", [])
    goals.append(
        {
            "name": context.user_data["current_goal_name"],
            "target_amount": context.user_data["current_goal_target"],
            "horizon_years": context.user_data["current_goal_horizon"],
            "priority": priority_raw,
        }
    )
    await update.message.reply_text(
        "Добавить еще одну цель?",
        reply_markup=_yes_no_keyboard(),
    )
    return GOAL_ADD_MORE


async def goal_add_more_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    decision = update.message.text.strip().lower()
    if decision == "да":
        await update.message.reply_text(
            "Введите название следующей цели.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return GOAL_NAME
    if decision != "нет":
        await update.message.reply_text("Пожалуйста, выберите 'Да' или 'Нет'.", reply_markup=_yes_no_keyboard())
        return GOAL_ADD_MORE

    if not context.user_data.get("goals"):
        await update.message.reply_text("Нужно добавить хотя бы одну цель.")
        return GOAL_NAME

    storage: UserStorage = context.application.bot_data["storage"]
    user_id = update.effective_user.id
    context.user_data["goals_json"] = json.dumps(context.user_data["goals"], ensure_ascii=False)
    profile = storage.from_context(context.user_data, user_id)
    storage.save_profile(profile)

    message = build_plan_message(profile)
    await update.message.reply_text(
        "Отлично, данные сохранены! Ниже ваш план:",
        reply_markup=ReplyKeyboardRemove(),
    )
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)
    return ConversationHandler.END


async def unrelated_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    if _is_finance_related(text):
        await update.message.reply_text(
            _message(context, "finance_redirect")
            + "\nЕсли вопрос узкоспециальный, могу не знать точный ответ."
        )
        return
    await update.message.reply_text(_message(context, "unrelated_refusal"))


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Диалог остановлен. Когда будете готовы продолжить — нажмите /start.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    LOGGER.exception("Unhandled exception: %s", context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(_message(context, "error_message"))


def register_handlers(application: Application) -> None:
    conversation = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, age_handler)],
            FAMILY_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, family_status_handler)],
            DEPENDENTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, dependents_handler)],
            MONTHLY_INCOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, income_handler)],
            MONTHLY_EXPENSES: [MessageHandler(filters.TEXT & ~filters.COMMAND, expenses_handler)],
            CURRENT_SAVINGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, current_savings_handler)],
            ASSET_REAL_ESTATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, asset_real_estate_handler)],
            ASSET_CARS: [MessageHandler(filters.TEXT & ~filters.COMMAND, asset_cars_handler)],
            ASSET_SECURITIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, asset_securities_handler)],
            ASSET_CRYPTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, asset_crypto_handler)],
            DEBT_MORTGAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, debt_mortgage_handler)],
            DEBT_CONSUMER: [MessageHandler(filters.TEXT & ~filters.COMMAND, debt_consumer_handler)],
            DEBT_OTHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, debt_other_handler)],
            RISK_PROFILE: [MessageHandler(filters.TEXT & ~filters.COMMAND, risk_profile_handler)],
            GOAL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, goal_name_handler)],
            GOAL_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, goal_target_handler)],
            GOAL_HORIZON: [MessageHandler(filters.TEXT & ~filters.COMMAND, goal_horizon_handler)],
            GOAL_PRIORITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, goal_priority_handler)],
            GOAL_ADD_MORE: [MessageHandler(filters.TEXT & ~filters.COMMAND, goal_add_more_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="finance_conversation",
        persistent=False,
    )

    application.add_handler(conversation)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("plan", plan))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, unrelated_message_handler)
    )
    application.add_error_handler(on_error)
