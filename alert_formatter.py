"""Construye los mensajes HTML que se envían a Telegram."""
from __future__ import annotations

from odds_tracker import LineDiffAlert, LineShiftAlert, MovementAlert


def _arrow(pct_change: float) -> str:
    return "🔺" if pct_change > 0 else "🔻"


def format_movement_alert(alert: MovementAlert, league: str, teams: str, score: str, minute: str) -> str:
    arrow = _arrow(alert.pct_change)
    line_txt = f" ({alert.line})" if alert.line is not None else ""
    return (
        f"💸 <b>Movimiento fuerte de cuota</b> {arrow}\n"
        f"⚽️ <b>{league}</b>\n"
        f"⏱ {minute}'  {teams}  {score}\n\n"
        f"<b>{alert.bookmaker}</b>\n"
        f"{alert.market_label}{line_txt}: "
        f"<s>{alert.old_odds:.2f}</s> ➜ <b>{alert.new_odds:.2f}</b> "
        f"({alert.pct_change:+.1f}%) en {int(alert.elapsed_seconds)}s\n\n"
        f"<i>Sin gol / roja / penalti en la ventana analizada → probable entrada fuerte de dinero.</i>"
    )


def format_line_shift_alert(alert: LineShiftAlert, league: str, teams: str, score: str, minute: str) -> str:
    return (
        f"📏 <b>Desplazamiento de línea</b>\n"
        f"⚽️ <b>{league}</b>\n"
        f"⏱ {minute}'  {teams}  {score}\n\n"
        f"<b>{alert.bookmaker}</b>\n"
        f"{alert.market_label}: línea principal "
        f"<s>{alert.old_line}</s> ➜ <b>{alert.new_line}</b> "
        f"en {int(alert.elapsed_seconds)}s\n\n"
        f"<i>Sin gol / roja / penalti en la ventana analizada → probable entrada fuerte de dinero.</i>"
    )


def format_line_diff_alert(alert: LineDiffAlert, league: str, teams: str, score: str, minute: str) -> str:
    return (
        f"⚖️ <b>Diferencia de línea entre casas</b>\n"
        f"⚽️ <b>{league}</b>\n"
        f"⏱ {minute}'  {teams}  {score}\n\n"
        f"{alert.market_label}\n"
        f"<b>{alert.bookmaker_a}</b>: {alert.line_a} @ {alert.odds_a:.2f}\n"
        f"<b>{alert.bookmaker_b}</b>: {alert.line_b} @ {alert.odds_b:.2f}\n\n"
        f"Δ línea = <b>{alert.diff}</b> goles"
    )
