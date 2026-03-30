"""Data models used by conversation and calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class UserFinancialProfile:
    user_id: int
    age: int
    family_status: str
    dependents: int
    monthly_income: float
    monthly_expenses: float
    current_savings: float
    assets_real_estate: float
    assets_cars: float
    assets_securities: float
    assets_crypto: float
    debt_mortgage: float
    debt_consumer: float
    debt_other: float
    risk_profile: str
    goals_json: str

    def total_assets(self) -> float:
        return (
            self.assets_real_estate
            + self.assets_cars
            + self.assets_securities
            + self.assets_crypto
            + self.current_savings
        )

    def total_debt(self) -> float:
        return self.debt_mortgage + self.debt_consumer + self.debt_other


@dataclass
class Goal:
    name: str
    target_amount: float
    horizon_years: int
    priority: str


AssetAllocation = Dict[str, float]
BudgetHints = List[str]
