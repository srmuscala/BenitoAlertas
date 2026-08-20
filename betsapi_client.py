"""
Cliente asíncrono para BetsAPI (https://betsapi.com/docs/).

Endpoints usados:
- GET /v3/events/inplay            -> lista de partidos en directo (con liga, marcador, minuto)
- GET /v1/bet365/inplay_filter      -> mapea event_id (BetsAPI) -> FI (id interno de Bet365)
- GET /v1/bet365/event?FI=...       -> odds/mercados en vivo de Bet365 para un partido
- GET /v1/betfair/ex/event?event_id -> odds de Betfair Exchange (back/lay) para un partido

Nota importante:
BetsAPI es un servicio de pago (desde ~10 USD/mes) que agrega datos de Bet365,
Betfair y otras casas. Si BetsAPI no encaja en tu presupuesto, alternativas con
API similar (odds en vivo + movimientos) son OddsJam, The Odds API (sin Betfair
Exchange nativo) u Odds-API.io. La estructura de este cliente es fácilmente
adaptable a cualquiera de ellas: solo cambian las URLs y el parseo de la
respuesta JSON.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

logger = logging.getLogger("betsapi_client")

BASE_URL = "https://api.b365api.com"

# Códigos de error que merece la pena reintentar (rate limit / error temporal del servidor)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class BetsAPIError(Exception):
    """Error no recuperable al hablar con BetsAPI."""


class BetsAPIClient:
    def __init__(
        self,
        token: str,
        session: aiohttp.ClientSession,
        max_concurrent_requests: int = 5,
        max_retries: int = 4,
        base_backoff_seconds: float = 2.0,
    ) -> None:
        self._token = token
        self._session = session
        self._semaphore = asyncio.Semaphore(max_concurrent_requests)
        self._max_retries = max_retries
        self._base_backoff = base_backoff_seconds

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = dict(params or {})
        params["token"] = self._token
        url = f"{BASE_URL}{path}"

        async with self._semaphore:
            for attempt in range(1, self._max_retries + 1):
                try:
                    async with self._session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("success") not in (1, "1", True):
                                logger.warning("BetsAPI respondió success=0 en %s: %s", path, data)
                            return data

                        body_preview = (await resp.text())[:300]

                        if resp.status in RETRYABLE_STATUS:
                            wait = self._base_backoff * (2 ** (attempt - 1))
                            logger.warning(
                                "BetsAPI %s -> HTTP %s (intento %d/%d). Reintentando en %.1fs. Body: %s",
                                path, resp.status, attempt, self._max_retries, wait, body_preview,
                            )
                            await asyncio.sleep(wait)
                            continue

                        # Error no recuperable (401 token inválido, 404, etc.)
                        raise BetsAPIError(f"HTTP {resp.status} en {path}: {body_preview}")

                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    wait = self._base_backoff * (2 ** (attempt - 1))
                    logger.warning(
                        "Fallo de red en %s (intento %d/%d): %s. Reintentando en %.1fs",
                        path, attempt, self._max_retries, exc, wait,
                    )
                    await asyncio.sleep(wait)

            logger.error("Se agotaron los reintentos para %s, se omite este ciclo.", path)
            raise BetsAPIError(f"Máximo de reintentos alcanzado para {path}")

    # ------------------------------------------------------------------ #
    # Endpoints públicos
    # ------------------------------------------------------------------ #

    async def get_inplay_events(self, sport_id: int = 1) -> list[dict[str, Any]]:
        """Partidos en directo. Incluye liga, equipos, marcador y minuto."""
        data = await self._get("/v3/events/inplay", {"sport_id": sport_id})
        return data.get("results", []) or []

    async def get_bet365_inplay_filter(self, sport_id: int = 1) -> list[dict[str, Any]]:
        """Mapea event_id (BetsAPI) <-> FI (id de Bet365) para eventos en directo."""
        data = await self._get("/v1/bet365/inplay_filter", {"sport_id": sport_id})
        return data.get("results", []) or []

    async def get_bet365_event(self, fi: str) -> dict[str, Any]:
        """Odds/mercados en vivo de Bet365 para un partido (por FI)."""
        data = await self._get("/v1/bet365/event", {"FI": fi})
        results = data.get("results", [])
        return results[0] if results else {}

    async def get_betfair_ex_event(self, event_id: str) -> dict[str, Any]:
        """Odds de Betfair Exchange (back/lay) para un partido."""
        data = await self._get("/v1/betfair/ex/event", {"event_id": event_id})
        results = data.get("results", [])
        return results[0] if results else {}
