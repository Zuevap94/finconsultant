"""Validation helpers for user input."""

from __future__ import annotations

import re


def parse_positive_int(raw_value: str, min_value: int = 0, max_value: int = 10_000) -> int:
    cleaned = raw_value.strip().lower().replace(" ", "")
    match = re.search(r"\d+", cleaned)
    if not match:
        raise ValueError("Integer value expected")
    value = int(match.group())
    if value < min_value or value > max_value:
        raise ValueError(f"Value must be between {min_value} and {max_value}")
    return value


def parse_non_negative_money(raw_value: str, max_value: float = 1_000_000_000_000.0) -> float:
    cleaned = raw_value.strip().lower()
    cleaned = cleaned.replace("\u00a0", " ")
    cleaned = re.sub(r"(руб(лей|ля|\.?)?|р\.?|₽)", "", cleaned)
    cleaned = cleaned.replace(" ", "").replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", cleaned):
        raise ValueError("Invalid money format")
    value = float(cleaned)
    if value < 0 or value > max_value:
        raise ValueError("Value out of accepted range")
    return value
