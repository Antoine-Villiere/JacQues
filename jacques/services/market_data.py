from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
import csv
import io
import re
import unicodedata
import calendar

import requests


_DATE_RE = re.compile(r"^\\d{4}-\\d{2}-\\d{2}$")
_YEAR_RE = re.compile(r"^\\d{4}$")
_YEAR_MONTH_RE = re.compile(r"^(\\d{4})-(\\d{1,2})$")
_RELATIVE_RE = re.compile(r"^(\\d+)\\s*(day|days|month|months|year|years|jour|jours|mois|an|ans|annee|annees)$")

_RELATIVE_TOKENS = {
    "last",
    "past",
    "ago",
    "il y a",
    "dernier",
    "derniers",
    "derniere",
    "dernieres",
}

_TODAY_WORDS = {
    "today",
    "now",
    "aujourdhui",
    "aujourd'hui",
}

_MONTHS = {
    "january": 1,
    "jan": 1,
    "janvier": 1,
    "janv": 1,
    "february": 2,
    "feb": 2,
    "fevrier": 2,
    "fev": 2,
    "march": 3,
    "mar": 3,
    "mars": 3,
    "april": 4,
    "apr": 4,
    "avril": 4,
    "may": 5,
    "mai": 5,
    "june": 6,
    "jun": 6,
    "juin": 6,
    "july": 7,
    "jul": 7,
    "juillet": 7,
    "juil": 7,
    "august": 8,
    "aug": 8,
    "aout": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "septembre": 9,
    "october": 10,
    "oct": 10,
    "octobre": 10,
    "november": 11,
    "nov": 11,
    "novembre": 11,
    "december": 12,
    "dec": 12,
    "decembre": 12,
}


def fetch_fred_series(
    series_id: str,
    start_date: str,
    end_date: str | None,
    timeout: int,
    max_points: int = 400,
) -> list[tuple[str, float]]:
    start_iso = _normalize_date(start_date, end=False)
    end_iso = _normalize_date(end_date, end=True) if end_date else date.today().isoformat()
    if start_iso > end_iso:
        raise ValueError("start_date must be before end_date")

    series_id = series_id.strip().upper()
    params = {"id": series_id, "cosd": start_iso, "coed": end_iso}
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()

    reader = csv.DictReader(io.StringIO(response.text))
    rows: list[tuple[str, float]] = []
    for row in reader:
        obs_date = (row.get("observation_date") or "").strip()
        value = (row.get(series_id) or row.get("value") or row.get("VALUE") or "").strip()
        if not obs_date or value in {"", "."}:
            continue
        try:
            rows.append((obs_date, float(value)))
        except ValueError:
            continue

    return _downsample(rows, max_points)


def fetch_stooq_history(
    symbol: str,
    start_date: str,
    end_date: str | None,
    timeout: int,
    max_points: int = 400,
) -> list[dict[str, float | int | str]]:
    if not symbol:
        raise ValueError("symbol is required")
    start_iso = _normalize_date(start_date, end=False)
    end_iso = _normalize_date(end_date, end=True) if end_date else date.today().isoformat()
    if start_iso > end_iso:
        raise ValueError("start_date must be before end_date")

    stooq_symbol = _normalize_stooq_symbol(symbol)
    url = "https://stooq.com/q/d/l/"
    params = {"s": stooq_symbol, "i": "d"}
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    if "No data" in response.text:
        return []

    reader = csv.DictReader(io.StringIO(response.text))
    rows: list[dict[str, float | int | str]] = []
    for row in reader:
        obs_date = (row.get("Date") or "").strip()
        if not obs_date:
            continue
        if obs_date < start_iso or obs_date > end_iso:
            continue
        close = _parse_float(row.get("Close"))
        if close is None:
            continue
        rows.append(
            {
                "date": obs_date,
                "open": _parse_float(row.get("Open")) or 0.0,
                "high": _parse_float(row.get("High")) or 0.0,
                "low": _parse_float(row.get("Low")) or 0.0,
                "close": close,
                "volume": _parse_int(row.get("Volume")) or 0,
            }
        )

    rows.sort(key=lambda item: str(item.get("date", "")))
    return _downsample_rows(rows, max_points)


def _downsample(data: list[tuple[str, float]], max_points: int) -> list[tuple[str, float]]:
    if max_points <= 0 or len(data) <= max_points:
        return data
    step = max(1, len(data) // max_points)
    sampled = data[::step]
    if sampled[-1] != data[-1]:
        sampled.append(data[-1])
    return sampled


def _downsample_rows(
    data: list[dict[str, float | int | str]], max_points: int
) -> list[dict[str, float | int | str]]:
    if max_points <= 0 or len(data) <= max_points:
        return data
    step = max(1, len(data) // max_points)
    sampled = data[::step]
    if sampled[-1] != data[-1]:
        sampled.append(data[-1])
    return sampled


def _normalize_stooq_symbol(symbol: str) -> str:
    cleaned = symbol.strip().lower()
    if not cleaned:
        return cleaned
    if cleaned.endswith(".us"):
        return cleaned
    if "." in cleaned:
        return f"{cleaned}.us"
    return f"{cleaned}.us"


def _parse_float(value: str | None) -> float | None:
    raw = (value or "").strip()
    if not raw or raw in {".", "NA", "N/A"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    raw = (value or "").strip()
    if not raw or raw in {".", "NA", "N/A"}:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _normalize_date(value: str | None, end: bool) -> str:
    if not value:
        raise ValueError("date is required")
    raw = value.strip()
    if raw:
        lowered = raw.lower()
        if lowered in _TODAY_WORDS:
            return date.today().isoformat()
        relative = _parse_relative_date(lowered)
        if relative:
            return relative
    if _DATE_RE.match(raw):
        return raw
    match = _YEAR_MONTH_RE.match(raw)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        day = _month_last_day(year, month) if end else 1
        return _format_date(year, month, day)
    if _YEAR_RE.match(raw):
        year = int(raw)
        month = 12 if end else 1
        day = _month_last_day(year, month) if end else 1
        return _format_date(year, month, day)

    normalized = _normalize_text(raw)
    tokens = normalized.split()
    if not tokens:
        raise ValueError("date is required")

    year = _find_year(tokens)
    if year is None:
        raise ValueError("date must include a year")
    month = _find_month(tokens)
    numbers = _numeric_tokens(tokens)
    day = None
    if month is None:
        month = 12 if end else 1
    for value in numbers:
        if value == year or value == month:
            continue
        if 1 <= value <= 31:
            day = value
            break
    if day is None:
        day = _month_last_day(year, month) if end else 1

    return _format_date(year, month, day)


def _parse_relative_date(text: str) -> str | None:
    cleaned = text.strip().lower()
    if not cleaned:
        return None
    for token in _RELATIVE_TOKENS:
        cleaned = cleaned.replace(token, " ")
    cleaned = " ".join(cleaned.split())
    match = _RELATIVE_RE.match(cleaned)
    if not match:
        return None
    count = int(match.group(1))
    if count <= 0:
        return None
    unit = match.group(2)
    today = date.today()
    if unit in {"day", "days", "jour", "jours"}:
        return (today - timedelta(days=count)).isoformat()
    if unit in {"month", "months", "mois"}:
        return _shift_months(today, -count).isoformat()
    if unit in {"year", "years", "an", "ans", "annee", "annees"}:
        year = today.year - count
        month = today.month
        day = min(today.day, _month_last_day(year, month))
        return date(year, month, day).isoformat()
    return None


def _shift_months(current: date, delta: int) -> date:
    month_index = current.month - 1 + delta
    year = current.year + month_index // 12
    month = month_index % 12 + 1
    day = min(current.day, _month_last_day(year, month))
    return date(year, month, day)


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return normalized.strip()


def _find_year(tokens: list[str]) -> int | None:
    for token in tokens:
        if token.isdigit() and len(token) == 4:
            year = int(token)
            if 1900 <= year <= 2100:
                return year
    return None


def _find_month(tokens: list[str]) -> int | None:
    for token in tokens:
        if token in _MONTHS:
            return _MONTHS[token]
    for token in tokens:
        if token.isdigit():
            value = int(token)
            if 1 <= value <= 12:
                return value
    return None


def _numeric_tokens(tokens: list[str]) -> list[int]:
    values = []
    for token in tokens:
        if token.isdigit():
            values.append(int(token))
    return values


def _month_last_day(year: int, month: int) -> int:
    if month < 1 or month > 12:
        raise ValueError("month must be between 1 and 12")
    return calendar.monthrange(year, month)[1]


def _format_date(year: int, month: int, day: int) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}"
