"""
Orquestador principal: en cada ciclo,
  1. Descarga los partidos en directo (fútbol, ligas menores).
  2. Para cada partido, descarga odds de Bet365 y Betfair Exchange.
  3. Parsea los mercados relevantes (1X2, O/U, DNB, Hándicap — HT y FT).
  4. Alimenta el OddsTracker (movimiento fuerte, desplazamiento de línea,
     diferencia de línea entre casas).
  5. Envía las alertas resultantes a Telegram.
"""
from __future__ import annotations

import asyncio
import logging

import aiohttp

from betsapi_client import BetsAPIClient, BetsAPIError
from config import Settings
from league_filter import extract_league_name, is_excluded_league
from market_parser import ParsedSelection, parse_bet365_event, parse_betfair_ex_event, pick_main_ou_line
from odds_tracker import OddsTracker

logger = logging.getLogger("monitor")

TRACKED_MARKET_BASES = ["1x2_ft", "1x2_ht", "ou_ft", "ou_ht", "dnb_ft", "dnb_ht", "handicap_ft", "handicap_ht"]


def get_red_cards(event: dict) -> int:
    """
    Best-effort: intenta leer el nº de tarjetas rojas del partido.
    AJUSTAR según el payload real de tu cuenta de BetsAPI (el campo puede
    llamarse distinto, ej. dentro de "stats" o de un endpoint de incidentes
    separado). Por defecto devuelve 0 (conservador: seguimos confiando
    principalmente en el cambio de marcador para descartar falsos positivos).
    """
    stats = event.get("stats") or {}
    try:
        home_rc = int(stats.get("redcards_home", 0) or 0)
        away_rc = int(stats.get("redcards_away", 0) or 0)
        return home_rc + away_rc
    except (TypeError, ValueError):
        return 0


def get_score(event: dict) -> str:
    return event.get("ss") or "0-0"


def get_minute(event: dict) -> str:
    timer = event.get("timer") or {}
    tm = timer.get("tm")
    return str(tm) if tm is not None else "?"


class Monitor:
    def __init__(self, settings: Settings, send_alert_fn) -> None:
        self._settings = settings
        self._send_alert = send_alert_fn
        self._tracker = OddsTracker(
            window_seconds=settings.odds_move_window_seconds,
            min_change_pct=settings.min_odds_change_pct,
            min_line_diff=settings.min_line_diff,
            cooldown_seconds=settings.alert_cooldown_minutes * 60,
        )
        self._cycle_count = 0

    async def run_forever(self) -> None:
        async with aiohttp.ClientSession() as session:
            client = BetsAPIClient(
                token=self._settings.betsapi_token,
                session=session,
                max_concurrent_requests=self._settings.max_concurrent_requests,
            )
            while True:
                started = asyncio.get_event_loop().time()
                try:
                    await self._run_cycle(client)
                except BetsAPIError as exc:
                    logger.error("Ciclo abortado por error de BetsAPI: %s", exc)
                except Exception:
                    logger.exception("Error inesperado en el ciclo de monitoreo")

                self._cycle_count += 1
                if self._cycle_count % 10 == 0:
                    self._tracker.cleanup()

                elapsed = asyncio.get_event_loop().time() - started
                sleep_for = max(1.0, self._settings.poll_interval_seconds - elapsed)
                await asyncio.sleep(sleep_for)

    async def _run_cycle(self, client: BetsAPIClient) -> None:
        events = await client.get_inplay_events(sport_id=self._settings.sport_id)
        relevant_events = [
            ev for ev in events
            if not is_excluded_league(extract_league_name(ev), self._settings.excluded_league_keywords)
        ]
        logger.info("Ciclo: %d partidos en directo, %d en ligas menores.", len(events), len(relevant_events))

        if not relevant_events:
            return

        fi_map = await self._build_fi_map(client)

        tasks = [self._process_event(client, ev, fi_map.get(str(ev.get("id")))) for ev in relevant_events]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _build_fi_map(self, client: BetsAPIClient) -> dict[str, str]:
        try:
            entries = await client.get_bet365_inplay_filter(sport_id=self._settings.sport_id)
        except BetsAPIError:
            logger.warning("No se pudo obtener el mapeo event_id -> FI de Bet365 en este ciclo.")
            return {}
        fi_map = {}
        for entry in entries:
            event_id = str(entry.get("BB") or entry.get("id") or "")
            fi = str(entry.get("FI") or "")
            if event_id and fi:
                fi_map[event_id] = fi
        return fi_map

    async def _process_event(self, client: BetsAPIClient, event: dict, fi: str | None) -> None:
        event_id = str(event.get("id"))
        league = extract_league_name(event)
        home = (event.get("home") or {}).get("name", "?")
        away = (event.get("away") or {}).get("name", "?")
        teams = f"{home} vs {away}"
        score = get_score(event)
        minute = get_minute(event)
        red_cards = get_red_cards(event)

        bet365_selections: list[ParsedSelection] = []
        betfair_selections: list[ParsedSelection] = []

        try:
            if fi:
                raw_bet365 = await client.get_bet365_event(fi)
                if raw_bet365:
                    bet365_selections = parse_bet365_event(raw_bet365)
        except BetsAPIError as exc:
            logger.warning("Bet365 event %s (FI=%s) falló: %s", event_id, fi, exc)

        try:
            raw_betfair = await client.get_betfair_ex_event(event_id)
            if raw_betfair:
                betfair_selections = parse_betfair_ex_event(raw_betfair)
        except BetsAPIError as exc:
            logger.warning("Betfair Exchange event %s falló: %s", event_id, exc)

        ctx = (league, teams, score, minute)

        if bet365_selections:
            await self._check_movements(event_id, "Bet365", bet365_selections, score, red_cards, ctx)
        if betfair_selections:
            await self._check_movements(event_id, "Betfair Exchange", betfair_selections, score, red_cards, ctx)

        if bet365_selections and betfair_selections:
            await self._check_cross_bookmaker(event_id, bet365_selections, betfair_selections, ctx)

    async def _check_movements(
        self,
        event_id: str,
        bookmaker: str,
        selections: list[ParsedSelection],
        score: str,
        red_cards: int,
        ctx: tuple[str, str, str, str],
    ) -> None:
        from alert_formatter import format_line_shift_alert, format_movement_alert

        league, teams, _score, minute = ctx

        for sel in selections:
            if sel.suspended or sel.odds is None:
                continue
            market_key = f"{sel.market_key}:{sel.selection}:{sel.line if sel.line is not None else 'NA'}"
            alert = self._tracker.record_and_check_movement(
                event_id=event_id,
                bookmaker=bookmaker,
                market_key=market_key,
                market_label=f"{sel.market_label} - {sel.selection.capitalize()}",
                line=sel.line,
                odds=sel.odds,
                current_score=score,
                current_red_cards=red_cards,
            )
            if alert:
                await self._send_alert(format_movement_alert(alert, league, teams, score, minute))

        for base in TRACKED_MARKET_BASES:
            if not base.startswith("ou") and not base.startswith("handicap"):
                continue
            main_line = pick_main_ou_line(selections, base)
            if main_line is None:
                continue
            label = next((s.market_label for s in selections if s.market_key == base), base)
            shift = self._tracker.record_and_check_line_shift(
                event_id=event_id,
                bookmaker=bookmaker,
                market_key=base,
                market_label=label,
                current_line=main_line,
                current_score=score,
                current_red_cards=red_cards,
            )
            if shift:
                await self._send_alert(format_line_shift_alert(shift, league, teams, score, minute))

    async def _check_cross_bookmaker(
        self,
        event_id: str,
        bet365_selections: list[ParsedSelection],
        betfair_selections: list[ParsedSelection],
        ctx: tuple[str, str, str, str],
    ) -> None:
        from alert_formatter import format_line_diff_alert

        league, teams, score, minute = ctx

        for base in TRACKED_MARKET_BASES:
            if not base.startswith("ou") and not base.startswith("handicap"):
                continue

            line_a = pick_main_ou_line(bet365_selections, base)
            line_b = pick_main_ou_line(betfair_selections, base)
            if line_a is None or line_b is None:
                continue

            odds_a = next(
                (s.odds for s in bet365_selections if s.market_key == base and s.selection == "over" and s.line == line_a),
                None,
            )
            odds_b = next(
                (s.odds for s in betfair_selections if s.market_key == base and s.selection == "over" and s.line == line_b),
                None,
            )
            label = next((s.market_label for s in bet365_selections if s.market_key == base), base)

            diff_alert = self._tracker.check_line_diff(
                event_id=event_id,
                market_key=base,
                market_label=label,
                bookmaker_a="Bet365",
                line_a=line_a,
                odds_a=odds_a,
                bookmaker_b="Betfair Exchange",
                line_b=line_b,
                odds_b=odds_b,
            )
            if diff_alert:
                await self._send_alert(format_line_diff_alert(diff_alert, league, teams, score, minute))
