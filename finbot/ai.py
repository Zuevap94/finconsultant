"""LLM-powered helpers: risk profiling, coaching tone, and voice transcription."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from finbot.finance import DISCLAIMER
from finbot.models import Goal, UserFinancialProfile

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AISettings:
    api_key: str
    model: str


def _build_client(settings: AISettings) -> OpenAI:
    return OpenAI(api_key=settings.api_key)


def infer_risk_profile(
    settings: Optional[AISettings],
    profile_dict: Dict[str, Any],
    goals: List[Dict[str, Any]],
) -> str:
    """
    Determine risk profile using LLM; fallback to heuristic.
    Returns one of: консервативный, умеренный, агрессивный.
    """
    fallback = _heuristic_risk_profile(profile_dict, goals)
    if settings is None or not settings.api_key:
        return fallback
    try:
        client = _build_client(settings)
        prompt = (
            "Ты финансовый ассистент. Определи риск-профиль пользователя "
            "на основе его возраста, доходов/расходов, долгов, целей и горизонта.\n"
            "Верни только JSON формата {\"risk_profile\":\"консервативный|умеренный|агрессивный\","
            "\"reason\":\"короткое объяснение\"}.\n"
            "Не добавляй ничего вне JSON."
        )
        response = client.chat.completions.create(
            model=settings.model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": "Ты точный и осторожный финансовый аналитик."},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"profile": profile_dict, "goals": goals},
                        ensure_ascii=False,
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed = json.loads(raw)
        risk = str(parsed.get("risk_profile", "")).strip().lower()
        if risk in {"консервативный", "умеренный", "агрессивный"}:
            return risk
        return fallback
    except Exception as exc:
        LOGGER.warning("LLM risk profiling failed, using fallback: %s", exc)
        return fallback


def infer_risk_profile_with_reason(
    settings: Optional[AISettings],
    profile_dict: Dict[str, Any],
    goals: List[Dict[str, Any]],
) -> Tuple[str, str]:
    """
    Determine risk profile and human-readable reason.
    Returns (risk_profile, reason).
    """
    fallback_risk = _heuristic_risk_profile(profile_dict, goals)
    fallback_reason = (
        "Оценка сделана по возрасту, долговой нагрузке, свободному денежному потоку "
        "и горизонту целей."
    )
    if settings is None or not settings.api_key:
        return fallback_risk, fallback_reason
    try:
        client = _build_client(settings)
        prompt = (
            "Ты финансовый ассистент. Определи риск-профиль пользователя "
            "на основе его возраста, доходов/расходов, долгов, целей и горизонта.\n"
            "Верни только JSON формата {\"risk_profile\":\"консервативный|умеренный|агрессивный\","
            "\"reason\":\"короткое объяснение\"}.\n"
            "Не добавляй ничего вне JSON."
        )
        response = client.chat.completions.create(
            model=settings.model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": "Ты точный и осторожный финансовый аналитик."},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"profile": profile_dict, "goals": goals},
                        ensure_ascii=False,
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed = json.loads(raw)
        risk = str(parsed.get("risk_profile", "")).strip().lower()
        reason = str(parsed.get("reason", "")).strip()
        if risk not in {"консервативный", "умеренный", "агрессивный"}:
            risk = fallback_risk
        if not reason:
            reason = fallback_reason
        return risk, reason
    except Exception as exc:
        LOGGER.warning("LLM risk profiling failed, using fallback: %s", exc)
        return fallback_risk, fallback_reason


def _heuristic_risk_profile(profile: Dict[str, Any], goals: List[Dict[str, Any]]) -> str:
    age = int(profile.get("age", 35))
    income = float(profile.get("monthly_income", 0))
    expenses = float(profile.get("monthly_expenses", 0))
    debt = (
        float(profile.get("debt_mortgage", 0))
        + float(profile.get("debt_consumer", 0))
        + float(profile.get("debt_other", 0))
    )
    free = income - expenses
    short_goal = any(int(goal.get("horizon_years", 100)) <= 3 for goal in goals)
    dti = debt / max(income * 12, 1)

    score = 0
    if age < 35:
        score += 2
    elif age < 50:
        score += 1

    if free > income * 0.25:
        score += 2
    elif free > income * 0.10:
        score += 1

    if dti > 0.5:
        score -= 2
    elif dti > 0.35:
        score -= 1

    if short_goal:
        score -= 1

    if score <= 0:
        return "консервативный"
    if score <= 3:
        return "умеренный"
    return "агрессивный"


def generate_human_recommendations(
    settings: Optional[AISettings],
    profile: UserFinancialProfile,
    goals: List[Goal],
) -> List[str]:
    """
    Create friendly, human-style recommendations.
    Falls back to deterministic suggestions if LLM unavailable.
    """
    fallback = _fallback_recommendations(profile, goals)
    if settings is None or not settings.api_key:
        return fallback
    try:
        client = _build_client(settings)
        payload = {
            "age": profile.age,
            "family_status": profile.family_status,
            "dependents": profile.dependents,
            "monthly_income": profile.monthly_income,
            "monthly_expenses": profile.monthly_expenses,
            "current_savings": profile.current_savings,
            "total_debt": profile.total_debt(),
            "risk_profile": profile.risk_profile,
            "goals": [
                {
                    "name": g.name,
                    "target_amount": g.target_amount,
                    "horizon_years": g.horizon_years,
                    "priority": g.priority,
                }
                for g in goals
            ],
        }
        system = (
            "Ты дружелюбный финансовый коуч. Говори по-человечески, поддерживай пользователя, "
            "без сложных терминов или с простым объяснением. "
            "Сформируй до 6 коротких практичных рекомендаций на русском."
        )
        user = (
            f"Составь рекомендации с акцентом на бюджет, долги, накопления, инвестиции и психологию дисциплины. "
            f"Последний пункт обязательно с фразой: '{DISCLAIMER}'"
        )
        response = client.chat.completions.create(
            model=settings.model,
            temperature=0.6,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                {"role": "user", "content": user},
            ],
        )
        text = (response.choices[0].message.content or "").strip()
        lines = [line.strip("•- \n\t") for line in text.splitlines() if line.strip()]
        lines = [line for line in lines if len(line) > 10]
        if not lines:
            return fallback
        # Keep concise and ensure disclaimer exists.
        result = lines[:6]
        if not any(DISCLAIMER in line for line in result):
            result.append(DISCLAIMER)
        return result
    except Exception as exc:
        LOGGER.warning("LLM recommendations failed, using fallback: %s", exc)
        return fallback


def suggest_funds_and_portfolio(
    settings: Optional[AISettings],
    profile: UserFinancialProfile,
    goals: List[Goal],
) -> List[str]:
    """
    Educational suggestions for fund categories and sample portfolio construction.
    Not tied to specific brokerage advice.
    """
    fallback = [
        "Для базы рассмотрите широкие индексные фонды на акции (российский и международный рынок) с низкими комиссиями.",
        "Стабилизирующая часть: фонды облигаций инвестиционного качества и/или короткие ОФЗ.",
        "Для краткосрочных целей (до 3 лет) — больше денежного рынка и облигаций, меньше акций.",
        "Ориентир структуры: 1-2 фонда акций + 1-2 фонда облигаций + денежный рынок для резервной части.",
        DISCLAIMER,
    ]
    if settings is None or not settings.api_key:
        return fallback
    try:
        client = _build_client(settings)
        payload = {
            "risk_profile": profile.risk_profile,
            "age": profile.age,
            "goals": [
                {"name": g.name, "horizon_years": g.horizon_years, "priority": g.priority}
                for g in goals
            ],
        }
        response = client.chat.completions.create(
            model=settings.model,
            temperature=0.4,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты финансовый консультант-обучатор. Дай 4-6 рекомендаций по категориям инвестиционных фондов "
                        "и составлению диверсифицированного портфеля. Никаких гарантий доходности."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                {"role": "user", "content": f"Пиши просто и добавь в конце: {DISCLAIMER}"},
            ],
        )
        text = (response.choices[0].message.content or "").strip()
        lines = [line.strip("•- \n\t") for line in text.splitlines() if line.strip()]
        lines = [line for line in lines if len(line) > 10][:6]
        if not lines:
            return fallback
        if not any(DISCLAIMER in line for line in lines):
            lines.append(DISCLAIMER)
        return lines
    except Exception as exc:
        LOGGER.warning("LLM funds suggestions failed, using fallback: %s", exc)
        return fallback


def transcribe_voice_note(
    settings: Optional[AISettings],
    audio_path: Path,
    model: str = "gpt-4o-mini-transcribe",
) -> Optional[str]:
    """Transcribe Telegram voice message into text."""
    if settings is None or not settings.api_key:
        return None
    try:
        client = _build_client(settings)
        with audio_path.open("rb") as fh:
            result = client.audio.transcriptions.create(model=model, file=fh)
        text = (getattr(result, "text", "") or "").strip()
        return text or None
    except Exception as exc:
        LOGGER.warning("Voice transcription failed: %s", exc)
        return None


def generate_coach_reply(
    settings: Optional[AISettings],
    user_text: str,
    profile: Optional[UserFinancialProfile] = None,
) -> Optional[str]:
    """Generate short, human, supportive finance reply for ad-hoc user questions."""
    if settings is None or not settings.api_key:
        return None
    try:
        client = _build_client(settings)
        payload: Dict[str, Any] = {"question": user_text}
        if profile is not None:
            payload["context"] = {
                "age": profile.age,
                "income": profile.monthly_income,
                "expenses": profile.monthly_expenses,
                "risk_profile": profile.risk_profile,
                "debt_total": profile.total_debt(),
            }
        response = client.chat.completions.create(
            model=settings.model,
            temperature=0.6,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты дружелюбный финансовый коуч. Отвечай по-русски, коротко, по делу, "
                        "по-человечески. Если вопрос вне финансового планирования — вежливо откажись. "
                        "Если нет точного ответа — прямо скажи об этом."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                {
                    "role": "user",
                    "content": (
                        "Дай до 5 предложений и добавь в конце фразу: "
                        f"'{DISCLAIMER}'"
                    ),
                },
            ],
        )
        text = (response.choices[0].message.content or "").strip()
        if not text:
            return None
        if DISCLAIMER not in text:
            text = f"{text}\n\n{DISCLAIMER}"
        return text
    except Exception as exc:
        LOGGER.warning("Coach reply generation failed: %s", exc)
        return None


def _fallback_recommendations(profile: UserFinancialProfile, goals: List[Goal]) -> List[str]:
    hints: List[str] = []
    free = profile.monthly_income - profile.monthly_expenses
    if free <= 0:
        hints.append("Сейчас баланс доходов и расходов напряженный — начнем мягко: сократите 2-3 необязательные траты уже в этом месяце.")
    else:
        hints.append("У вас уже есть потенциал для роста капитала — отличный фундамент, продолжайте в том же духе.")
    hints.append("Настройте автоматический перевод на накопления в день зарплаты, даже если это 5-10% дохода.")
    if profile.total_debt() > 0:
        hints.append("Сфокусируйтесь на погашении самых дорогих кредитов: это часто дает самый быстрый финансовый эффект.")
    if any(goal.horizon_years <= 3 for goal in goals):
        hints.append("Для краткосрочных целей лучше больше надежных инструментов и меньше волатильных активов.")
    hints.append("Двигайтесь маленькими шагами: стабильность важнее идеального плана в теории.")
    hints.append(DISCLAIMER)
    return hints
