"""Persistence layer backed by SQLite."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

from finbot.models import UserFinancialProfile


class UserStorage:
    """Simple SQLite storage for user profile snapshots."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    age INTEGER NOT NULL,
                    family_status TEXT NOT NULL,
                    dependents INTEGER NOT NULL,
                    monthly_income REAL NOT NULL,
                    monthly_expenses REAL NOT NULL,
                    current_savings REAL NOT NULL,
                    assets_real_estate REAL NOT NULL,
                    assets_cars REAL NOT NULL,
                    assets_securities REAL NOT NULL,
                    assets_crypto REAL NOT NULL,
                    debt_mortgage REAL NOT NULL,
                    debt_consumer REAL NOT NULL,
                    debt_other REAL NOT NULL,
                    risk_profile TEXT NOT NULL,
                    goals_json TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def save_profile(self, profile: UserFinancialProfile) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (
                    user_id, age, family_status, dependents, monthly_income,
                    monthly_expenses, current_savings, assets_real_estate,
                    assets_cars, assets_securities, assets_crypto, debt_mortgage,
                    debt_consumer, debt_other, risk_profile, goals_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    age=excluded.age,
                    family_status=excluded.family_status,
                    dependents=excluded.dependents,
                    monthly_income=excluded.monthly_income,
                    monthly_expenses=excluded.monthly_expenses,
                    current_savings=excluded.current_savings,
                    assets_real_estate=excluded.assets_real_estate,
                    assets_cars=excluded.assets_cars,
                    assets_securities=excluded.assets_securities,
                    assets_crypto=excluded.assets_crypto,
                    debt_mortgage=excluded.debt_mortgage,
                    debt_consumer=excluded.debt_consumer,
                    debt_other=excluded.debt_other,
                    risk_profile=excluded.risk_profile,
                    goals_json=excluded.goals_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    profile.user_id,
                    profile.age,
                    profile.family_status,
                    profile.dependents,
                    profile.monthly_income,
                    profile.monthly_expenses,
                    profile.current_savings,
                    profile.assets_real_estate,
                    profile.assets_cars,
                    profile.assets_securities,
                    profile.assets_crypto,
                    profile.debt_mortgage,
                    profile.debt_consumer,
                    profile.debt_other,
                    profile.risk_profile,
                    profile.goals_json,
                ),
            )

    def get_profile(self, user_id: int) -> Optional[UserFinancialProfile]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return UserFinancialProfile(
            user_id=row["user_id"],
            age=row["age"],
            family_status=row["family_status"],
            dependents=row["dependents"],
            monthly_income=row["monthly_income"],
            monthly_expenses=row["monthly_expenses"],
            current_savings=row["current_savings"],
            assets_real_estate=row["assets_real_estate"],
            assets_cars=row["assets_cars"],
            assets_securities=row["assets_securities"],
            assets_crypto=row["assets_crypto"],
            debt_mortgage=row["debt_mortgage"],
            debt_consumer=row["debt_consumer"],
            debt_other=row["debt_other"],
            risk_profile=row["risk_profile"],
            goals_json=row["goals_json"],
        )

    def delete_profile(self, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))

    def has_profile(self, user_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM users WHERE user_id = ? LIMIT 1",
                (user_id,),
            ).fetchone()
        return row is not None

    @staticmethod
    def from_context(context_data: Dict[str, Any], user_id: int) -> UserFinancialProfile:
        """Convert in-memory conversation data to the typed profile model."""
        return UserFinancialProfile(
            user_id=user_id,
            age=int(context_data["age"]),
            family_status=str(context_data["family_status"]),
            dependents=int(context_data["dependents"]),
            monthly_income=float(context_data["monthly_income"]),
            monthly_expenses=float(context_data["monthly_expenses"]),
            current_savings=float(context_data["current_savings"]),
            assets_real_estate=float(context_data["assets_real_estate"]),
            assets_cars=float(context_data["assets_cars"]),
            assets_securities=float(context_data["assets_securities"]),
            assets_crypto=float(context_data["assets_crypto"]),
            debt_mortgage=float(context_data["debt_mortgage"]),
            debt_consumer=float(context_data["debt_consumer"]),
            debt_other=float(context_data["debt_other"]),
            risk_profile=str(context_data["risk_profile"]),
            goals_json=str(context_data["goals_json"]),
        )
