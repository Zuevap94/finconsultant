"""PDF report generation with charts for personal finance plans."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from finbot.finance import AnalysisResult, DISCLAIMER, parse_diagnostic_notes, parse_goals
from finbot.models import Goal, UserFinancialProfile


def _register_fonts() -> str:
    # DejaVu Sans is widely available on Linux and supports Cyrillic.
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            pdfmetrics.registerFont(TTFont("DejaVuSans", path))
            return "DejaVuSans"
    return "Helvetica"


def _chart_asset_allocation(allocation: Dict[str, float], output_png: Path) -> None:
    labels = list(allocation.keys())
    sizes = list(allocation.values())
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=140)
    ax.set_title("Распределение активов")
    plt.tight_layout()
    fig.savefig(output_png, dpi=140)
    plt.close(fig)


def _chart_cashflow(profile: UserFinancialProfile, output_png: Path) -> None:
    categories = ["Доход", "Расходы", "Свободный\nпоток"]
    free = profile.monthly_income - profile.monthly_expenses
    values = [profile.monthly_income, profile.monthly_expenses, free]
    colors_set = ["#2E7D32", "#C62828", "#1565C0" if free >= 0 else "#EF6C00"]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.bar(categories, values, color=colors_set)
    ax.set_title("Денежный поток (в месяц, ₽)")
    ax.grid(axis="y", alpha=0.25)
    plt.tight_layout()
    fig.savefig(output_png, dpi=140)
    plt.close(fig)


def build_pdf_report(
    profile: UserFinancialProfile,
    analysis: AnalysisResult,
    allocation: Dict[str, float],
    budget_hints: List[str],
    goal_strategies: List[Tuple[str, str]],
    human_recommendations: List[str],
    fund_recommendations: List[str],
    output_pdf: Path,
    artifacts_dir: Path,
) -> Path:
    """Create a detailed PDF report with charts and recommendations."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    base_font = _register_fonts()

    pie_path = artifacts_dir / f"allocation_{profile.user_id}.png"
    cashflow_path = artifacts_dir / f"cashflow_{profile.user_id}.png"

    _chart_asset_allocation(allocation, pie_path)
    _chart_cashflow(profile, cashflow_path)

    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    heading = styles["Heading1"]
    heading2 = styles["Heading2"]
    heading.fontName = base_font
    heading2.fontName = base_font
    normal.fontName = base_font

    doc = SimpleDocTemplate(str(output_pdf), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm)
    elements = []
    goals = parse_goals(profile.goals_json)
    diagnostic_notes = parse_diagnostic_notes(profile.diagnostic_notes_json)

    elements.append(Paragraph("Персональный финансовый отчет", heading))
    elements.append(Paragraph(datetime.now().strftime("Дата формирования: %d.%m.%Y %H:%M"), normal))
    elements.append(Spacer(1, 8))

    summary_data = [
        ["Показатель", "Значение"],
        ["Возраст", str(profile.age)],
        ["Семейный статус", profile.family_status],
        ["Иждивенцы", str(profile.dependents)],
        ["Доход (мес)", f"{profile.monthly_income:,.0f} ₽".replace(",", " ")],
        ["Расходы (мес)", f"{profile.monthly_expenses:,.0f} ₽".replace(",", " ")],
        ["Свободный поток", f"{analysis.monthly_free_cashflow:,.0f} ₽".replace(",", " ")],
        ["Коэффициент сбережения", f"{analysis.savings_ratio * 100:.1f}%"],
        ["Debt-to-Income", f"{analysis.debt_to_income_ratio * 100:.1f}%"],
        ["Цель резервного фонда", f"{analysis.emergency_fund_target:,.0f} ₽".replace(",", " ")],
    ]
    summary_table = Table(summary_data, colWidths=[70 * mm, 100 * mm])
    summary_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), base_font),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    elements.append(summary_table)
    elements.append(Spacer(1, 10))

    if diagnostic_notes:
        elements.append(Paragraph("Живая диагностика: контекст и мотивация", heading2))
        grouped: Dict[str, List[Dict[str, str]]] = {}
        for note in diagnostic_notes:
            grouped.setdefault(note.get("block", "Контекст"), []).append(note)
        for block_name, notes in grouped.items():
            elements.append(Paragraph(f"<b>{block_name}</b>", normal))
            for note in notes[:3]:
                question = note.get("question", "")
                answer = note.get("answer", "")
                if question and answer:
                    elements.append(Paragraph(f"• {question} → {answer}", normal))
        elements.append(Spacer(1, 10))

    elements.append(Paragraph("Графики", heading2))
    elements.append(Image(str(cashflow_path), width=170 * mm, height=95 * mm))
    elements.append(Spacer(1, 6))
    elements.append(Image(str(pie_path), width=170 * mm, height=100 * mm))
    elements.append(Spacer(1, 10))

    alloc_data = [["Класс активов", "Доля"]] + [[k, f"{v:.1f}%"] for k, v in allocation.items()]
    alloc_table = Table(alloc_data, colWidths=[120 * mm, 50 * mm])
    alloc_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), base_font),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]
        )
    )
    elements.append(Paragraph("Распределение активов", heading2))
    elements.append(alloc_table)
    elements.append(Spacer(1, 10))

    elements.append(Paragraph("Живые рекомендации", heading2))
    for line in human_recommendations:
        elements.append(Paragraph(f"• {line}", normal))
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("Рекомендации по фондам и портфелю (образовательные)", heading2))
    for line in fund_recommendations:
        elements.append(Paragraph(f"• {line}", normal))
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("Пошаговые действия", heading2))
    for hint in budget_hints:
        elements.append(Paragraph(f"• {hint}", normal))
    elements.append(Spacer(1, 6))

    elements.append(Paragraph("Цели и ориентиры сроков", heading2))
    if goals:
        for goal_name, goal_summary in goal_strategies:
            elements.append(Paragraph(f"• <b>{goal_name}</b>: {goal_summary}", normal))
    else:
        elements.append(Paragraph("• Цели пока не заполнены.", normal))
    elements.append(Spacer(1, 10))

    elements.append(Paragraph(f"⚠️ {DISCLAIMER}", normal))
    doc.build(elements)
    return output_pdf
