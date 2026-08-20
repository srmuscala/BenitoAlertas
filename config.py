"""
Carga de configuración desde variables de entorno (.env).
Centraliza todos los parámetros ajustables del bot para no tener
"números mágicos" repartidos por el código.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _get_env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(
            f"Falta la variable de entorno obligatoria '{name}'. "
            f"Revisa tu archivo .env (usa .env.example como plantilla)."
        )
    return value


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: str
    betsapi_token: str

    sport_id: int
    poll_interval_seconds: int
    min_odds_change_pct: float
    odds_move_window_seconds: int
    min_line_diff: float
    alert_cooldown_minutes: int
    max_concurrent_requests: int

    excluded_league_keywords: list[str] = field(default_factory=list)


def load_settings() -> Settings:
    excluded_raw = _get_env("EXCLUDED_LEAGUE_KEYWORDS", default="")
    excluded = [kw.strip().lower() for kw in excluded_raw.split(",") if kw.strip()]

    return Settings(
        telegram_bot_token=_get_env("TELEGRAM_BOT_TOKEN", required=True),
        telegram_chat_id=_get_env("TELEGRAM_CHAT_ID", required=True),
        betsapi_token=_get_env("BETSAPI_TOKEN", required=True),
        sport_id=_get_int("SPORT_ID", 1),
        poll_interval_seconds=_get_int("POLL_INTERVAL_SECONDS", 60),
        min_odds_change_pct=_get_float("MIN_ODDS_CHANGE_PCT", 8.0),
        odds_move_window_seconds=_get_int("ODDS_MOVE_WINDOW_SECONDS", 300),
        min_line_diff=_get_float("MIN_LINE_DIFF", 0.5),
        alert_cooldown_minutes=_get_int("ALERT_COOLDOWN_MINUTES", 30),
        max_concurrent_requests=_get_int("MAX_CONCURRENT_REQUESTS", 5),
        excluded_league_keywords=excluded,
    )


settings = load_settings()
