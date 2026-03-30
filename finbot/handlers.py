"""Telegram handlers and conversation flow."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
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

from finbot.ai import (
    AISettings,
    generate_coach_reply,
    generate_human_recommendations,
    infer_risk_profile_with_reason,
    suggest_funds_and_portfolio,
    transcribe_voice_note,
)
from finbot.finance import DISCLAIMER, build_plan_message, build_plan_payload
from finbot.pdf_report import build_pdf_report
from finbot.storage import UserStorage
from finbot.validators import parse_non_negative_money, parse_positive_int

LOGGER = logging.getLogger(__name__)

ALLOWED_GOAL_HINTS = (
    "покупка жилья, финансовая подушка, образование детей, пенсия, капитал на бизнес"
)

DEFAULT_MESSAGES = {
    "disclaimer": DISCLAIMER,
    "start_welcome": (
        "Привет! Я ваш финансовый помощник 👋\n"
        "Я общаюсь простым языком, понимаю голосовые и соберу для вас персональный план.\n\n"
        "Начнем с возраста. Напишите или наговорите число (например, 30)."
    ),
    "help_text": (
        "Команды:\n"
        "/start — начать сбор данных\n"
        "/plan — показать персональный план\n"
        "/pdf — скачать детальный PDF-отчет с графиками\n"
        "/reset — удалить сохраненные данные\n"
        "/help — справка\n\n"
        "Можно отправлять и голосовые сообщения — я постараюсь распознать их.\n"
        "Я отвечаю только на темы финансового планирования. {disclaimer}"
    ),
    "reset_done": "Готово, данные очищены. Для нового расчета нажмите /start.",
    "plan_no_data": "Пока нет сохраненных данных. Нажмите /start, и я быстро проведу вас по вопросам.",
    "unrelated_refusal": (
        "Я специализируюсь только на финансовом планировании. "
        "Давайте вернемся к вашему плану: используйте /start или /plan."
    ),
    "finance_redirect": (
        "Отличный вопрос по финансам. Могу ответить коротко или собрать полный персональный план через /start."
    ),
    "error_message": "Поймал техническую ошибку. Попробуйте еще раз или используйте /start.",
    "goal_examples": ALLOWED_GOAL_HINTS,
}

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
    GOAL_NAME,
    GOAL_TARGET,
    GOAL_HORIZON,
    GOAL_PRIORITY,
    GOAL_ADD_MORE,
) = range(18)

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
    "портфель",
    "фонд",
    "облигац",
    "акци",
)

USER_INPUT_FILTER = (filters.TEXT | filters.VOICE) & ~filters.COMMAND
CUSTOM_INPUT_LABEL = "Ввести свое"


def _message(context: ContextTypes.DEFAULT_TYPE, key: str) -> str:
    messages = context.application.bot_data.get("messages", {})
    template = str(messages.get(key, DEFAULT_MESSAGES.get(key, "")))
    return template.format(
        disclaimer=messages.get("disclaimer", DEFAULT_MESSAGES["disclaimer"])
    )


def _family_status_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("Холост/Не замужем"), KeyboardButton("Женат/Замужем")],
            [KeyboardButton("В разводе"), KeyboardButton("Другое")],
        ],
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


def _quick_amount_keyboard(*amounts: str) -> ReplyKeyboardMarkup:
    row1 = [KeyboardButton(value) for value in amounts[:2]]
    row2 = [KeyboardButton(value) for value in amounts[2:4]] if len(amounts) > 2 else []
    keyboard = [row1]
    if row2:
        keyboard.append(row2)
    keyboard.append([KeyboardButton(CUSTOM_INPUT_LABEL)])
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _age_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("25"), KeyboardButton("35"), KeyboardButton("45"), KeyboardButton("55")], [KeyboardButton(CUSTOM_INPUT_LABEL)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _dependents_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("0"), KeyboardButton("1"), KeyboardButton("2"), KeyboardButton("3+")], [KeyboardButton(CUSTOM_INPUT_LABEL)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _goal_horizon_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("1"), KeyboardButton("3"), KeyboardButton("5"), KeyboardButton("10"), KeyboardButton("20")], [KeyboardButton(CUSTOM_INPUT_LABEL)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _goal_name_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("Финансовая подушка"), KeyboardButton("Покупка жилья")],
            [KeyboardButton("Пенсия"), KeyboardButton("Образование детей")],
            [KeyboardButton(CUSTOM_INPUT_LABEL)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _is_finance_related(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in FINANCE_KEYWORDS)


def _get_ai_settings(context: ContextTypes.DEFAULT_TYPE) -> Optional[AISettings]:
    return context.application.bot_data.get("ai_settings")


def _normalize_yes_no(text: str) -> Optional[bool]:
    lowered = text.lower().strip()
    if lowered.startswith("да"):
        return True
    if lowered.startswith("нет"):
        return False
    return None


def _normalize_priority(text: str) -> Optional[str]:
    lowered = text.lower().strip()
    if lowered.startswith("выс"):
        return "высокий"
    if lowered.startswith("сре"):
        return "средний"
    if lowered.startswith("низ"):
        return "низкий"
    return None


def _is_custom_input(text: str) -> bool:
    return text.strip().lower() == CUSTOM_INPUT_LABEL.lower()


async def _extract_user_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state_hint: str = "",
) -> Optional[str]:
    message = update.effective_message
    if message is None:
        return None
    if message.text:
        return message.text.strip()

    if message.voice:
        ai_settings = _get_ai_settings(context)
        if ai_settings is None or not ai_settings.api_key:
            await message.reply_text(
                "Я могу распознавать голосовые, но сейчас не настроен AI-ключ. "
                "Пожалуйста, отправьте это сообщение текстом."
            )
            return None
        try:
            voice_dir = Path("data/voice")
            voice_dir.mkdir(parents=True, exist_ok=True)
            voice_file = await message.voice.get_file()
            out_path = voice_dir / f"{update.effective_user.id}_{message.message_id}.ogg"
            await voice_file.download_to_drive(custom_path=str(out_path))
            transcript = transcribe_voice_note(ai_settings, out_path)
            if not transcript:
                await message.reply_text(
                    "Не смог надежно распознать голосовое. Повторите, пожалуйста, текстом или другим голосовым."
                )
                return None
            await message.reply_text(f"Распознал так: «{transcript}»")
            return transcript.strip()
        except Exception:
            LOGGER.exception("Voice extraction failed")
            await message.reply_text(
                f"Не получилось обработать голосовое на шаге '{state_hint}'. Попробуйте текстом."
            )
            return None
    return None


def _validate_money_step(raw: str) -> Optional[float]:
    try:
        return parse_non_negative_money(raw)
    except Exception:
        return None


def _build_llm_personalization(
    context: ContextTypes.DEFAULT_TYPE,
    profile: Any,
) -> tuple[List[str], List[str]]:
    payload = build_plan_payload(profile)
    ai_settings = _get_ai_settings(context)
    human = generate_human_recommendations(ai_settings, profile, payload.goals)
    funds = suggest_funds_and_portfolio(ai_settings, profile, payload.goals)
    return human, funds


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    context.user_data["goals"] = []
    await update.message.reply_text(
        _message(context, "start_welcome"),
        reply_markup=_age_keyboard(),
    )
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
    human, funds = _build_llm_personalization(context, profile)
    message = build_plan_message(
        profile,
        risk_reason=profile.risk_note,
        human_recommendations=human,
        fund_recommendations=funds,
    )
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)


async def pdf_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage: UserStorage = context.application.bot_data["storage"]
    user_id = update.effective_user.id
    profile = storage.get_profile(user_id)
    if profile is None:
        await update.message.reply_text(_message(context, "plan_no_data"))
        return

    payload = build_plan_payload(profile)
    human, funds = _build_llm_personalization(context, profile)
    reports_dir = Path("data/reports")
    charts_dir = reports_dir / "charts"
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_path = reports_dir / f"finance_plan_{user_id}_{timestamp}.pdf"

    try:
        build_pdf_report(
            profile=profile,
            analysis=payload.analysis,
            allocation=payload.allocation,
            budget_hints=payload.budget_hints,
            goal_strategies=payload.strategies,
            human_recommendations=human,
            fund_recommendations=funds,
            output_pdf=pdf_path,
            artifacts_dir=charts_dir,
        )
        with pdf_path.open("rb") as fh:
            await update.message.reply_document(
                document=fh,
                filename=pdf_path.name,
                caption=(
                    "Готово! Отправил подробный PDF-отчет с графиками и персональными рекомендациями.\n"
                    f"⚠️ {DISCLAIMER}"
                ),
            )
    except Exception:
        LOGGER.exception("PDF generation failed")
        await update.message.reply_text(
            "Не удалось собрать PDF-отчет. Попробуйте чуть позже или запросите /plan."
        )


async def age_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = await _extract_user_text(update, context, "age")
    if text is None:
        return AGE
    if _is_custom_input(text):
        await update.message.reply_text(
            "Введите возраст числом от 18 до 100.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return AGE
    try:
        age = parse_positive_int(text, min_value=18, max_value=100)
    except Exception:
        await update.message.reply_text(
            "Введите возраст числом от 18 до 100.",
            reply_markup=_age_keyboard(),
        )
        return AGE
    context.user_data["age"] = age
    await update.message.reply_text(
        "Укажите семейный статус:",
        reply_markup=_family_status_keyboard(),
    )
    return FAMILY_STATUS


async def family_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = await _extract_user_text(update, context, "family_status")
    if text is None:
        return FAMILY_STATUS
    if len(text.strip()) < 2:
        await update.message.reply_text("Выберите семейный статус кнопкой или напишите коротко (например: женат).")
        return FAMILY_STATUS
    context.user_data["family_status"] = text.strip()
    await update.message.reply_text(
        "Сколько у вас иждивенцев? (число, можно 0)",
        reply_markup=_dependents_keyboard(),
    )
    return DEPENDENTS


async def dependents_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = await _extract_user_text(update, context, "dependents")
    if text is None:
        return DEPENDENTS
    if _is_custom_input(text):
        await update.message.reply_text(
            "Введите количество иждивенцев числом (можно 0).",
            reply_markup=ReplyKeyboardRemove(),
        )
        return DEPENDENTS
    try:
        dependents = parse_positive_int(text, min_value=0, max_value=20)
    except Exception:
        await update.message.reply_text(
            "Введите число от 0 до 20.",
            reply_markup=_dependents_keyboard(),
        )
        return DEPENDENTS
    context.user_data["dependents"] = dependents
    await update.message.reply_text(
        "Ваш средний доход в месяц (в ₽)? Выберите вариант или введите свое значение.",
        reply_markup=_quick_amount_keyboard("80 000 ₽", "120 000 ₽", "180 000 ₽", "250 000 ₽"),
    )
    return MONTHLY_INCOME


async def income_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = await _extract_user_text(update, context, "monthly_income")
    if text is None:
        return MONTHLY_INCOME
    if _is_custom_input(text):
        await update.message.reply_text(
            "Введите сумму дохода, например: 120000",
            reply_markup=ReplyKeyboardRemove(),
        )
        return MONTHLY_INCOME
    value = _validate_money_step(text)
    if value is None or value <= 0:
        await update.message.reply_text(
            "Введите корректную сумму дохода больше 0.",
            reply_markup=_quick_amount_keyboard("80 000 ₽", "120 000 ₽", "180 000 ₽", "250 000 ₽"),
        )
        return MONTHLY_INCOME
    context.user_data["monthly_income"] = value
    await update.message.reply_text(
        "Основные расходы в месяц (в ₽)? Выберите вариант или введите свое значение.",
        reply_markup=_quick_amount_keyboard("40 000 ₽", "70 000 ₽", "100 000 ₽", "140 000 ₽"),
    )
    return MONTHLY_EXPENSES


async def expenses_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = await _extract_user_text(update, context, "monthly_expenses")
    if text is None:
        return MONTHLY_EXPENSES
    if _is_custom_input(text):
        await update.message.reply_text(
            "Введите сумму расходов, например: 70000",
            reply_markup=ReplyKeyboardRemove(),
        )
        return MONTHLY_EXPENSES
    value = _validate_money_step(text)
    if value is None:
        await update.message.reply_text(
            "Введите корректную сумму расходов.",
            reply_markup=_quick_amount_keyboard("40 000 ₽", "70 000 ₽", "100 000 ₽", "140 000 ₽"),
        )
        return MONTHLY_EXPENSES
    context.user_data["monthly_expenses"] = value
    await update.message.reply_text(
        "Текущие сбережения (в ₽)?",
        reply_markup=_quick_amount_keyboard("0 ₽", "100 000 ₽", "300 000 ₽", "1 000 000 ₽"),
    )
    return CURRENT_SAVINGS


async def current_savings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = await _extract_user_text(update, context, "current_savings")
    if text is None:
        return CURRENT_SAVINGS
    if _is_custom_input(text):
        await update.message.reply_text(
            "Введите сумму сбережений, например: 300000",
            reply_markup=ReplyKeyboardRemove(),
        )
        return CURRENT_SAVINGS
    value = _validate_money_step(text)
    if value is None:
        await update.message.reply_text(
            "Введите корректную сумму сбережений.",
            reply_markup=_quick_amount_keyboard("0 ₽", "100 000 ₽", "300 000 ₽", "1 000 000 ₽"),
        )
        return CURRENT_SAVINGS
    context.user_data["current_savings"] = value
    await update.message.reply_text(
        "Стоимость вашей недвижимости (в ₽, если нет — 0).",
        reply_markup=_quick_amount_keyboard("0 ₽", "3 000 000 ₽", "6 000 000 ₽", "10 000 000 ₽"),
    )
    return ASSET_REAL_ESTATE


async def asset_real_estate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = await _extract_user_text(update, context, "assets_real_estate")
    if text is None:
        return ASSET_REAL_ESTATE
    if _is_custom_input(text):
        await update.message.reply_text(
            "Введите стоимость недвижимости, например: 6000000",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ASSET_REAL_ESTATE
    value = _validate_money_step(text)
    if value is None:
        await update.message.reply_text(
            "Введите корректную сумму недвижимости.",
            reply_markup=_quick_amount_keyboard("0 ₽", "3 000 000 ₽", "6 000 000 ₽", "10 000 000 ₽"),
        )
        return ASSET_REAL_ESTATE
    context.user_data["assets_real_estate"] = value
    await update.message.reply_text(
        "Стоимость автомобилей (в ₽, если нет — 0).",
        reply_markup=_quick_amount_keyboard("0 ₽", "500 000 ₽", "1 000 000 ₽", "2 000 000 ₽"),
    )
    return ASSET_CARS


async def asset_cars_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = await _extract_user_text(update, context, "assets_cars")
    if text is None:
        return ASSET_CARS
    if _is_custom_input(text):
        await update.message.reply_text(
            "Введите стоимость автомобилей, например: 1000000",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ASSET_CARS
    value = _validate_money_step(text)
    if value is None:
        await update.message.reply_text(
            "Введите корректную сумму по автомобилям.",
            reply_markup=_quick_amount_keyboard("0 ₽", "500 000 ₽", "1 000 000 ₽", "2 000 000 ₽"),
        )
        return ASSET_CARS
    context.user_data["assets_cars"] = value
    await update.message.reply_text(
        "Стоимость ценных бумаг (в ₽, если нет — 0).",
        reply_markup=_quick_amount_keyboard("0 ₽", "200 000 ₽", "500 000 ₽", "1 500 000 ₽"),
    )
    return ASSET_SECURITIES


async def asset_securities_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = await _extract_user_text(update, context, "assets_securities")
    if text is None:
        return ASSET_SECURITIES
    if _is_custom_input(text):
        await update.message.reply_text(
            "Введите стоимость ценных бумаг, например: 500000",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ASSET_SECURITIES
    value = _validate_money_step(text)
    if value is None:
        await update.message.reply_text(
            "Введите корректную сумму по ценным бумагам.",
            reply_markup=_quick_amount_keyboard("0 ₽", "200 000 ₽", "500 000 ₽", "1 500 000 ₽"),
        )
        return ASSET_SECURITIES
    context.user_data["assets_securities"] = value
    await update.message.reply_text(
        "Стоимость криптовалют (в ₽, если нет — 0).",
        reply_markup=_quick_amount_keyboard("0 ₽", "50 000 ₽", "150 000 ₽", "500 000 ₽"),
    )
    return ASSET_CRYPTO


async def asset_crypto_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = await _extract_user_text(update, context, "assets_crypto")
    if text is None:
        return ASSET_CRYPTO
    if _is_custom_input(text):
        await update.message.reply_text(
            "Введите стоимость криптовалют, например: 150000",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ASSET_CRYPTO
    value = _validate_money_step(text)
    if value is None:
        await update.message.reply_text(
            "Введите корректную сумму по криптовалютам.",
            reply_markup=_quick_amount_keyboard("0 ₽", "50 000 ₽", "150 000 ₽", "500 000 ₽"),
        )
        return ASSET_CRYPTO
    context.user_data["assets_crypto"] = value
    await update.message.reply_text(
        "Остаток по ипотеке (в ₽, если нет — 0).",
        reply_markup=_quick_amount_keyboard("0 ₽", "1 500 000 ₽", "3 000 000 ₽", "5 000 000 ₽"),
    )
    return DEBT_MORTGAGE


async def debt_mortgage_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = await _extract_user_text(update, context, "debt_mortgage")
    if text is None:
        return DEBT_MORTGAGE
    if _is_custom_input(text):
        await update.message.reply_text(
            "Введите остаток по ипотеке, например: 3000000",
            reply_markup=ReplyKeyboardRemove(),
        )
        return DEBT_MORTGAGE
    value = _validate_money_step(text)
    if value is None:
        await update.message.reply_text(
            "Введите корректную сумму ипотеки.",
            reply_markup=_quick_amount_keyboard("0 ₽", "1 500 000 ₽", "3 000 000 ₽", "5 000 000 ₽"),
        )
        return DEBT_MORTGAGE
    context.user_data["debt_mortgage"] = value
    await update.message.reply_text(
        "Потребительские кредиты (в ₽, если нет — 0).",
        reply_markup=_quick_amount_keyboard("0 ₽", "100 000 ₽", "300 000 ₽", "700 000 ₽"),
    )
    return DEBT_CONSUMER


async def debt_consumer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = await _extract_user_text(update, context, "debt_consumer")
    if text is None:
        return DEBT_CONSUMER
    if _is_custom_input(text):
        await update.message.reply_text(
            "Введите сумму потребительских кредитов, например: 300000",
            reply_markup=ReplyKeyboardRemove(),
        )
        return DEBT_CONSUMER
    value = _validate_money_step(text)
    if value is None:
        await update.message.reply_text(
            "Введите корректную сумму потребительских кредитов.",
            reply_markup=_quick_amount_keyboard("0 ₽", "100 000 ₽", "300 000 ₽", "700 000 ₽"),
        )
        return DEBT_CONSUMER
    context.user_data["debt_consumer"] = value
    await update.message.reply_text(
        "Прочие долги (в ₽, если нет — 0).",
        reply_markup=_quick_amount_keyboard("0 ₽", "50 000 ₽", "150 000 ₽", "400 000 ₽"),
    )
    return DEBT_OTHER


async def debt_other_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = await _extract_user_text(update, context, "debt_other")
    if text is None:
        return DEBT_OTHER
    if _is_custom_input(text):
        await update.message.reply_text(
            "Введите сумму прочих долгов, например: 150000",
            reply_markup=ReplyKeyboardRemove(),
        )
        return DEBT_OTHER
    value = _validate_money_step(text)
    if value is None:
        await update.message.reply_text(
            "Введите корректную сумму прочих долгов.",
            reply_markup=_quick_amount_keyboard("0 ₽", "50 000 ₽", "150 000 ₽", "400 000 ₽"),
        )
        return DEBT_OTHER
    context.user_data["debt_other"] = value
    context.user_data["goals"] = []
    await update.message.reply_text(
        "Теперь финансовые цели.\n"
        f"Введите первую цель (например: {_message(context, 'goal_examples')}).\n"
        "Можно голосом.",
        reply_markup=_goal_name_keyboard(),
    )
    return GOAL_NAME


async def goal_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = await _extract_user_text(update, context, "goal_name")
    if text is None:
        return GOAL_NAME
    if _is_custom_input(text):
        await update.message.reply_text(
            "Введите название цели в свободной форме.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return GOAL_NAME
    name = text.strip()
    if len(name) < 2:
        await update.message.reply_text(
            "Название цели слишком короткое. Введите чуть подробнее.",
            reply_markup=_goal_name_keyboard(),
        )
        return GOAL_NAME
    context.user_data["current_goal_name"] = name
    await update.message.reply_text(
        "Какую сумму хотите накопить для этой цели (в ₽)?",
        reply_markup=_quick_amount_keyboard("300 000 ₽", "1 000 000 ₽", "3 000 000 ₽", "10 000 000 ₽"),
    )
    return GOAL_TARGET


async def goal_target_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = await _extract_user_text(update, context, "goal_target")
    if text is None:
        return GOAL_TARGET
    if _is_custom_input(text):
        await update.message.reply_text(
            "Введите сумму цели в рублях, например: 3000000",
            reply_markup=ReplyKeyboardRemove(),
        )
        return GOAL_TARGET
    value = _validate_money_step(text)
    if value is None or value == 0:
        await update.message.reply_text(
            "Введите корректную сумму больше 0.",
            reply_markup=_quick_amount_keyboard("300 000 ₽", "1 000 000 ₽", "3 000 000 ₽", "10 000 000 ₽"),
        )
        return GOAL_TARGET
    context.user_data["current_goal_target"] = value
    await update.message.reply_text(
        "За сколько лет хотите достичь цели? (1-50)",
        reply_markup=_goal_horizon_keyboard(),
    )
    return GOAL_HORIZON


async def goal_horizon_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = await _extract_user_text(update, context, "goal_horizon")
    if text is None:
        return GOAL_HORIZON
    if _is_custom_input(text):
        await update.message.reply_text(
            "Введите горизонт цели числом (от 1 до 50 лет).",
            reply_markup=ReplyKeyboardRemove(),
        )
        return GOAL_HORIZON
    try:
        horizon = parse_positive_int(text, min_value=1, max_value=50)
    except Exception:
        await update.message.reply_text(
            "Введите число от 1 до 50.",
            reply_markup=_goal_horizon_keyboard(),
        )
        return GOAL_HORIZON
    context.user_data["current_goal_horizon"] = horizon
    await update.message.reply_text(
        "Приоритет цели?",
        reply_markup=_goal_priority_keyboard(),
    )
    return GOAL_PRIORITY


async def goal_priority_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = await _extract_user_text(update, context, "goal_priority")
    if text is None:
        return GOAL_PRIORITY
    priority = _normalize_priority(text)
    if priority is None:
        await update.message.reply_text("Выберите приоритет кнопкой: Высокий, Средний или Низкий.")
        return GOAL_PRIORITY

    goals: List[Dict[str, Any]] = context.user_data.setdefault("goals", [])
    goals.append(
        {
            "name": context.user_data["current_goal_name"],
            "target_amount": context.user_data["current_goal_target"],
            "horizon_years": context.user_data["current_goal_horizon"],
            "priority": priority,
        }
    )
    await update.message.reply_text(
        "Добавить еще одну цель?",
        reply_markup=_yes_no_keyboard(),
    )
    return GOAL_ADD_MORE


async def goal_add_more_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = await _extract_user_text(update, context, "goal_add_more")
    if text is None:
        return GOAL_ADD_MORE
    decision = _normalize_yes_no(text)
    if decision is True:
        await update.message.reply_text(
            "Введите название следующей цели.",
            reply_markup=_goal_name_keyboard(),
        )
        return GOAL_NAME
    if decision is None:
        await update.message.reply_text(
            "Пожалуйста, выберите 'Да' или 'Нет'.",
            reply_markup=_yes_no_keyboard(),
        )
        return GOAL_ADD_MORE

    if not context.user_data.get("goals"):
        await update.message.reply_text("Нужно добавить хотя бы одну цель.")
        return GOAL_NAME

    context.user_data["goals_json"] = json.dumps(
        context.user_data["goals"],
        ensure_ascii=False,
    )
    ai_settings = _get_ai_settings(context)
    risk_profile, risk_reason = infer_risk_profile_with_reason(
        ai_settings,
        context.user_data,
        context.user_data["goals"],
    )
    context.user_data["risk_profile"] = risk_profile
    context.user_data["risk_note"] = risk_reason

    storage: UserStorage = context.application.bot_data["storage"]
    user_id = update.effective_user.id
    profile = storage.from_context(context.user_data, user_id)
    storage.save_profile(profile)

    human, funds = _build_llm_personalization(context, profile)
    message = build_plan_message(
        profile,
        risk_reason=profile.risk_note,
        human_recommendations=human,
        fund_recommendations=funds,
    )
    await update.message.reply_text(
        "Отлично, готово! Вы молодец, что дошли до конца.\n"
        "Я автоматически определил ваш риск-профиль и собрал персональный план 👇",
        reply_markup=ReplyKeyboardRemove(),
    )
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)
    await update.message.reply_text(
        "Если хотите красивый отчет с графиками — отправьте /pdf"
    )
    return ConversationHandler.END


async def unrelated_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = await _extract_user_text(update, context, "free_dialog")
    if not text:
        return

    storage: UserStorage = context.application.bot_data["storage"]
    profile = storage.get_profile(update.effective_user.id)
    ai_settings = _get_ai_settings(context)
    if _is_finance_related(text):
        ai_reply = generate_coach_reply(ai_settings, text, profile)
        if ai_reply:
            await update.message.reply_text(ai_reply)
            return
        await update.message.reply_text(
            _message(context, "finance_redirect")
            + "\nЕсли вопрос очень узкий, могу не знать точный ответ.\n"
            f"⚠️ {DISCLAIMER}"
        )
        return
    await update.message.reply_text(_message(context, "unrelated_refusal"))


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Остановил диалог. Когда будете готовы продолжить — нажмите /start.",
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
            AGE: [MessageHandler(USER_INPUT_FILTER, age_handler)],
            FAMILY_STATUS: [MessageHandler(USER_INPUT_FILTER, family_status_handler)],
            DEPENDENTS: [MessageHandler(USER_INPUT_FILTER, dependents_handler)],
            MONTHLY_INCOME: [MessageHandler(USER_INPUT_FILTER, income_handler)],
            MONTHLY_EXPENSES: [MessageHandler(USER_INPUT_FILTER, expenses_handler)],
            CURRENT_SAVINGS: [MessageHandler(USER_INPUT_FILTER, current_savings_handler)],
            ASSET_REAL_ESTATE: [MessageHandler(USER_INPUT_FILTER, asset_real_estate_handler)],
            ASSET_CARS: [MessageHandler(USER_INPUT_FILTER, asset_cars_handler)],
            ASSET_SECURITIES: [MessageHandler(USER_INPUT_FILTER, asset_securities_handler)],
            ASSET_CRYPTO: [MessageHandler(USER_INPUT_FILTER, asset_crypto_handler)],
            DEBT_MORTGAGE: [MessageHandler(USER_INPUT_FILTER, debt_mortgage_handler)],
            DEBT_CONSUMER: [MessageHandler(USER_INPUT_FILTER, debt_consumer_handler)],
            DEBT_OTHER: [MessageHandler(USER_INPUT_FILTER, debt_other_handler)],
            GOAL_NAME: [MessageHandler(USER_INPUT_FILTER, goal_name_handler)],
            GOAL_TARGET: [MessageHandler(USER_INPUT_FILTER, goal_target_handler)],
            GOAL_HORIZON: [MessageHandler(USER_INPUT_FILTER, goal_horizon_handler)],
            GOAL_PRIORITY: [MessageHandler(USER_INPUT_FILTER, goal_priority_handler)],
            GOAL_ADD_MORE: [MessageHandler(USER_INPUT_FILTER, goal_add_more_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="finance_conversation",
        persistent=False,
    )

    application.add_handler(conversation)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("plan", plan))
    application.add_handler(CommandHandler("pdf", pdf_report))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(MessageHandler(USER_INPUT_FILTER, unrelated_message_handler))
    application.add_error_handler(on_error)
