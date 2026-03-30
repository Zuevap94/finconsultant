"""Financial analysis and planning logic."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from math import ceil
from typing import Dict, List, Tuple

from finbot.models import Goal, UserFinancialProfile


DISCLAIMER = "Это не является финансовой рекомендацией."


@dataclass
class AnalysisResult:
    savings_ratio: float
    debt_to_income_ratio: float
    emergency_fund_target: float
    emergency_fund_gap: float
    total_assets: float
    total_debt: float
    net_worth: float
    monthly_free_cashflow: float


def parse_goals(goals_json: str) -> List[Goal]:
    try:
        data = json.loads(goals_json)
    except json.JSONDecodeError:
        return []
    goals: List[Goal] = []
    for item in data:
        try:
            goals.append(
                Goal(
                    name=str(item["name"]),
                    target_amount=float(item["target_amount"]),
                    horizon_years=int(item["horizon_years"]),
                    priority=str(item["priority"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return goals


def analyze_profile(profile: UserFinancialProfile) -> AnalysisResult:
    income = max(profile.monthly_income, 1.0)
    free_cashflow = profile.monthly_income - profile.monthly_expenses
    savings_ratio = max(free_cashflow, 0.0) / income
    debt_to_income_ratio = profile.total_debt() / (income * 12.0)
    emergency_months = 6 if profile.dependents > 0 else 4
    emergency_target = profile.monthly_expenses * emergency_months
    emergency_gap = max(0.0, emergency_target - profile.current_savings)
    total_assets = profile.total_assets()
    total_debt = profile.total_debt()
    net_worth = total_assets - total_debt

    return AnalysisResult(
        savings_ratio=savings_ratio,
        debt_to_income_ratio=debt_to_income_ratio,
        emergency_fund_target=emergency_target,
        emergency_fund_gap=emergency_gap,
        total_assets=total_assets,
        total_debt=total_debt,
        net_worth=net_worth,
        monthly_free_cashflow=free_cashflow,
    )


def _risk_stock_cap(risk_profile: str) -> float:
    risk_map = {
        "консервативный": 0.30,
        "умеренный": 0.50,
        "агрессивный": 0.70,
    }
    return risk_map.get(risk_profile.lower(), 0.50)


def _goal_adjustment(goals: List[Goal]) -> float:
    if not goals:
        return 0.0
    min_horizon = min(goal.horizon_years for goal in goals)
    if min_horizon <= 3:
        return -0.10
    if min_horizon <= 7:
        return -0.03
    return 0.05


def calculate_asset_allocation(profile: UserFinancialProfile, goals: List[Goal]) -> Dict[str, float]:
    """Return allocation across required classes with percentages that sum to 100."""
    # Age rule: (100 - age) roughly indicates equity share.
    base_stocks = max(0.20, min(0.80, (100 - profile.age) / 100.0))
    # Risk multiplier caps aggressive assets according to profile:
    # conservative=30%, moderate=50%, aggressive=70%.
    risk_cap = _risk_stock_cap(profile.risk_profile)
    stock_target = min(base_stocks, risk_cap)
    stock_target = max(0.15, min(0.85, stock_target + _goal_adjustment(goals)))

    short_goals = any(goal.horizon_years <= 3 for goal in goals)
    cash = 0.15 if short_goals else 0.08
    crypto = 0.02 if profile.risk_profile.lower() == "консервативный" else 0.05
    if profile.risk_profile.lower() == "агрессивный":
        crypto = 0.08

    alternatives = 0.03 if profile.risk_profile.lower() != "агрессивный" else 0.05
    real_estate = 0.10 if any("жиль" in goal.name.lower() for goal in goals) else 0.08

    fixed_bucket = cash + crypto + alternatives + real_estate
    remaining = max(0.10, 1.0 - fixed_bucket)
    stocks = min(stock_target, remaining * 0.75)
    bonds = max(0.05, remaining - stocks)

    domestic_stocks = stocks * 0.45
    foreign_stocks = stocks * 0.55

    allocation = {
        "Акции отечественные": domestic_stocks,
        "Акции иностранные": foreign_stocks,
        "Облигации": bonds,
        "Недвижимость": real_estate,
        "Денежные средства": cash,
        "Альтернативные активы": alternatives,
        "Криптовалюты": crypto,
    }

    total = sum(allocation.values())
    # Normalize in case of floating point drift.
    normalized = {k: (v / total) * 100 for k, v in allocation.items()}

    # Round and fix any integer rounding mismatch.
    rounded = {k: round(v, 1) for k, v in normalized.items()}
    diff = round(100.0 - sum(rounded.values()), 1)
    if abs(diff) >= 0.1:
        first_key = next(iter(rounded))
        rounded[first_key] = round(rounded[first_key] + diff, 1)
    return rounded


def build_budget_hints(profile: UserFinancialProfile, analysis: AnalysisResult) -> List[str]:
    hints: List[str] = []
    expenses_ratio = profile.monthly_expenses / max(profile.monthly_income, 1.0)
    if expenses_ratio > 0.8:
        hints.append("Расходы выше 80% дохода. Попробуйте снизить необязательные траты на 10-15%.")
    else:
        hints.append("Сохраняйте долю расходов до 70-75% дохода — это ускорит накопления.")

    if analysis.debt_to_income_ratio > 0.4:
        hints.append("Высокая долговая нагрузка: направляйте свободные деньги на погашение дорогих кредитов.")
    elif analysis.total_debt > 0:
        hints.append("Долговая нагрузка умеренная. Поддерживайте платежи без просрочек и не берите новые займы без необходимости.")
    else:
        hints.append("Долгов нет — это сильная позиция для ускоренного накопления капитала.")

    if analysis.emergency_fund_gap > 0:
        monthly_emergency = max(profile.monthly_income * 0.10, 1.0)
        months = ceil(analysis.emergency_fund_gap / monthly_emergency)
        hints.append(
            f"Резервный фонд стоит увеличить на {analysis.emergency_fund_gap:,.0f} ₽. "
            f"Если откладывать ~{monthly_emergency:,.0f} ₽/мес, потребуется около {months} мес."
        )
    else:
        hints.append("Резервный фонд уже на хорошем уровне. Держите его в надежных и ликвидных инструментах.")

    return hints


def goal_strategy(goals: List[Goal], monthly_free_cashflow: float) -> List[Tuple[str, str]]:
    if not goals:
        return [("Финансовые цели", "Цели пока не заполнены. Добавьте их через /reset и повторный диалог.")]

    available = max(monthly_free_cashflow, 0.0)
    weighted_sum = 0.0
    for goal in goals:
        priority_weight = {"высокий": 1.7, "средний": 1.0, "низкий": 0.6}.get(goal.priority.lower(), 1.0)
        urgency_weight = 1 / max(goal.horizon_years, 1)
        weighted_sum += priority_weight * urgency_weight

    results: List[Tuple[str, str]] = []
    for goal in goals:
        priority_weight = {"высокий": 1.7, "средний": 1.0, "низкий": 0.6}.get(goal.priority.lower(), 1.0)
        urgency_weight = 1 / max(goal.horizon_years, 1)
        share = (priority_weight * urgency_weight) / max(weighted_sum, 1e-6)
        monthly_for_goal = available * share
        months_to_goal = (
            ceil(goal.target_amount / monthly_for_goal)
            if monthly_for_goal > 0
            else None
        )
        if months_to_goal is None:
            summary = "Сейчас нет свободного денежного потока для этой цели."
        else:
            summary = (
                f"Рекомендуемый взнос: ~{monthly_for_goal:,.0f} ₽/мес. "
                f"Оценка достижения: ~{months_to_goal} мес "
                f"(горизонт цели: {goal.horizon_years} лет)."
            )
        results.append((goal.name, summary))
    return results


def _format_money(value: float) -> str:
    return f"{value:,.0f} ₽".replace(",", " ")


def build_plan_message(profile: UserFinancialProfile) -> str:
    goals = parse_goals(profile.goals_json)
    analysis = analyze_profile(profile)
    allocation = calculate_asset_allocation(profile, goals)
    budget_hints = build_budget_hints(profile, analysis)
    strategies = goal_strategy(goals, analysis.monthly_free_cashflow)

    lines: List[str] = []
    lines.append("📊 <b>Ваш персональный финансовый план</b>")
    lines.append("")
    lines.append("<b>1) Текущая финансовая картина</b>")
    lines.append(f"• Доход: {_format_money(profile.monthly_income)}/мес")
    lines.append(f"• Расходы: {_format_money(profile.monthly_expenses)}/мес")
    lines.append(f"• Свободный поток: {_format_money(analysis.monthly_free_cashflow)}/мес")
    lines.append(f"• Сбережения: {_format_money(profile.current_savings)}")
    lines.append(f"• Всего активов: {_format_money(analysis.total_assets)}")
    lines.append(f"• Всего долгов: {_format_money(analysis.total_debt)}")
    lines.append(f"• Чистый капитал: {_format_money(analysis.net_worth)}")
    lines.append(f"• Коэффициент сбережения: {analysis.savings_ratio * 100:.1f}%")
    lines.append(f"• Соотношение долга к доходу: {analysis.debt_to_income_ratio * 100:.1f}%")
    lines.append(
        f"• Резервный фонд: цель {_format_money(analysis.emergency_fund_target)}, "
        f"дефицит {_format_money(analysis.emergency_fund_gap)}"
    )
    lines.append("")
    lines.append("<b>2) Рекомендации по бюджету</b>")
    for hint in budget_hints:
        lines.append(f"• {hint}")
    lines.append("")
    lines.append("<b>3) Пошаговый план накоплений</b>")
    lines.append("• Шаг 1: Сформируйте/доведите резервный фонд до целевого уровня.")
    lines.append("• Шаг 2: Погасите дорогие кредиты (если ставка выше доходности инвестиций).")
    lines.append("• Шаг 3: Настройте автоматическое инвестирование в день зарплаты.")
    lines.append("• Шаг 4: Пересматривайте план каждые 3-6 месяцев.")
    lines.append("")
    lines.append("<b>4) Распределение активов (ориентир)</b>")
    lines.append("<pre>Класс активов              Доля")
    lines.append("--------------------------------")
    for asset_class, pct in allocation.items():
        lines.append(f"{asset_class:<25} {pct:>4.1f}%")
    lines.append("</pre>")
    lines.append("")
    lines.append("<b>5) Временная шкала целей</b>")
    for goal_name, summary in strategies:
        lines.append(f"• <b>{html.escape(goal_name)}</b>: {html.escape(summary)}")
    lines.append("")
    lines.append(f"⚠️ {DISCLAIMER}")
    return "\n".join(lines)
