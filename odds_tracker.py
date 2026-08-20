"""
Núcleo de la estrategia:

1) Movimiento fuerte de cuota/línea en una misma casa (Bet365 o Betfair Exchange)
   -> se compara cada cuota nueva contra la última registrada en una ventana de
      tiempo (ODDS_MOVE_WINDOW_SECONDS). Si el cambio % supera el umbral, es
      candidato a alerta.
   -> Para descartar que el movimiento se deba a un gol / roja / penalti, se
      compara el marcador y el nº de tarjetas rojas del partido ANTES y DESPUÉS
      de la ventana. Si cambiaron, se asume que el movimiento es "normal"
      (causado por el juego) y NO se avisa. Si el marcador y las rojas se
      mantienen igual, el movimiento solo puede explicarse por entrada de
      dinero / cambio de percepción del mercado -> se avisa.

2) Diferencia de línea entre casas para el mismo mercado (ej. Bet365 Over 1.5
   vs Betfair Exchange Over 2.25 en el mismo partido) -> se avisa si la
   diferencia de línea supera MIN_LINE_DIFF.

Importante: los nombres exactos de los campos de "incidentes" (roja, penalti)
pueden variar según el deporte/torneo en la respuesta real de BetsAPI. Aquí se
usa el marcador (siempre fiable) como señal principal de "algo pasó en el
campo", y un hook opcional para tarjetas que debes ajustar contra el payload
real de tu cuenta (ver README, sección "Ajustar a tu payload real").
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Snapshot:
    line: float | None
    odds: float
    timestamp: float
    score: str
    red_cards: int


@dataclass
class MovementAlert:
    event_id: str
    bookmaker: str
    market_key: str
    market_label: str
    line: float | None
    old_odds: float
    new_odds: float
    pct_change: float
    elapsed_seconds: float


@dataclass
class LineDiffAlert:
    event_id: str
    market_key: str
    market_label: str
    bookmaker_a: str
    line_a: float
    odds_a: float
    bookmaker_b: str
    line_b: float
    odds_b: float
    diff: float


class OddsTracker:
    def __init__(
        self,
        window_seconds: int,
        min_change_pct: float,
        min_line_diff: float,
        cooldown_seconds: int,
    ) -> None:
        self._window_seconds = window_seconds
        self._min_change_pct = min_change_pct
        self._min_line_diff = min_line_diff
        self._cooldown_seconds = cooldown_seconds

        # (event_id, bookmaker, market_key) -> lista de snapshots dentro de la ventana
        self._history: dict[tuple[str, str, str], list[Snapshot]] = {}
        # alert_key -> timestamp del último aviso (para no repetir)
        self._alert_cooldowns: dict[str, float] = {}

    # ------------------------------------------------------------------ #
    # Utilidades internas
    # ------------------------------------------------------------------ #

    def _in_cooldown(self, alert_key: str, now: float) -> bool:
        last = self._alert_cooldowns.get(alert_key)
        return last is not None and (now - last) < self._cooldown_seconds

    def _register_alert(self, alert_key: str, now: float) -> None:
        self._alert_cooldowns[alert_key] = now

    def cleanup(self) -> None:
        """Llamar periódicamente para no acumular memoria indefinidamente."""
        now = time.time()
        stale_alerts = [k for k, ts in self._alert_cooldowns.items() if now - ts > self._cooldown_seconds * 3]
        for k in stale_alerts:
            self._alert_cooldowns.pop(k, None)

        for key, snaps in list(self._history.items()):
            trimmed = [s for s in snaps if now - s.timestamp <= self._window_seconds * 2]
            if trimmed:
                self._history[key] = trimmed
            else:
                self._history.pop(key, None)

    # ------------------------------------------------------------------ #
    # 1) Movimiento fuerte de cuota (misma casa)
    # ------------------------------------------------------------------ #

    def record_and_check_movement(
        self,
        event_id: str,
        bookmaker: str,
        market_key: str,
        market_label: str,
        line: float | None,
        odds: float,
        current_score: str,
        current_red_cards: int,
    ) -> MovementAlert | None:
        now = time.time()
        key = (event_id, bookmaker, market_key)
        history = self._history.setdefault(key, [])

        # Baseline: snapshot más antiguo dentro de la ventana de tiempo
        history[:] = [s for s in history if now - s.timestamp <= self._window_seconds]
        baseline = history[0] if history else None

        history.append(Snapshot(line=line, odds=odds, timestamp=now, score=current_score, red_cards=current_red_cards))

        if baseline is None or baseline.odds <= 0:
            return None

        pct_change = (odds - baseline.odds) / baseline.odds * 100.0
        if abs(pct_change) < self._min_change_pct:
            return None

        # Si el marcador o las rojas cambiaron durante la ventana -> movimiento
        # explicado por el juego (gol / expulsión), no avisamos.
        if current_score != baseline.score:
            return None
        if current_red_cards != baseline.red_cards:
            return None

        alert_key = f"{event_id}:{bookmaker}:{market_key}:{round(line, 2) if line is not None else 'NA'}"
        if self._in_cooldown(alert_key, now):
            return None

        self._register_alert(alert_key, now)
        return MovementAlert(
            event_id=event_id,
            bookmaker=bookmaker,
            market_key=market_key,
            market_label=market_label,
            line=line,
            old_odds=baseline.odds,
            new_odds=odds,
            pct_change=pct_change,
            elapsed_seconds=now - baseline.timestamp,
        )

    # ------------------------------------------------------------------ #
    # 2) Diferencia de línea entre Bet365 y Betfair Exchange
    # ------------------------------------------------------------------ #

    def check_line_diff(
        self,
        event_id: str,
        market_key: str,
        market_label: str,
        bookmaker_a: str,
        line_a: float | None,
        odds_a: float | None,
        bookmaker_b: str,
        line_b: float | None,
        odds_b: float | None,
    ) -> LineDiffAlert | None:
        if line_a is None or line_b is None or odds_a is None or odds_b is None:
            return None

        diff = round(abs(line_a - line_b), 3)
        if diff < self._min_line_diff:
            return None

        now = time.time()
        alert_key = f"linediff:{event_id}:{market_key}:{round(line_a, 2)}:{round(line_b, 2)}"
        if self._in_cooldown(alert_key, now):
            return None

        self._register_alert(alert_key, now)
        return LineDiffAlert(
            event_id=event_id,
            market_key=market_key,
            market_label=market_label,
            bookmaker_a=bookmaker_a,
            line_a=line_a,
            odds_a=odds_a,
            bookmaker_b=bookmaker_b,
            line_b=line_b,
            odds_b=odds_b,
            diff=diff,
        )

    # ------------------------------------------------------------------ #
    # 3) Desplazamiento de la línea "principal" de Over/Under o Handicap
    #    (misma casa) — típico movimiento por entrada fuerte de dinero
    #    cuando la casa reajusta toda la línea en vez de solo la cuota.
    # ------------------------------------------------------------------ #

    def record_and_check_line_shift(
        self,
        event_id: str,
        bookmaker: str,
        market_key: str,
        market_label: str,
        current_line: float,
        current_score: str,
        current_red_cards: int,
    ) -> "LineShiftAlert | None":
        now = time.time()
        key = (event_id, bookmaker, f"lineshift:{market_key}")
        history = self._history.setdefault(key, [])
        history[:] = [s for s in history if now - s.timestamp <= self._window_seconds]
        baseline = history[0] if history else None

        history.append(Snapshot(line=current_line, odds=0.0, timestamp=now, score=current_score, red_cards=current_red_cards))

        if baseline is None or baseline.line is None:
            return None

        diff = round(abs(current_line - baseline.line), 3)
        if diff < self._min_line_diff:
            return None
        if current_score != baseline.score or current_red_cards != baseline.red_cards:
            return None

        alert_key = f"lineshift:{event_id}:{bookmaker}:{market_key}"
        if self._in_cooldown(alert_key, now):
            return None
        self._register_alert(alert_key, now)

        return LineShiftAlert(
            event_id=event_id,
            bookmaker=bookmaker,
            market_key=market_key,
            market_label=market_label,
            old_line=baseline.line,
            new_line=current_line,
            elapsed_seconds=now - baseline.timestamp,
        )


@dataclass
class LineShiftAlert:
    event_id: str
    bookmaker: str
    market_key: str
    market_label: str
    old_line: float
    new_line: float
    elapsed_seconds: float
