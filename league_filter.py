"""
Filtro para descartar las ligas "grandes" (Premier League, LaLiga, Serie A, etc.)
y quedarnos solo con ligas menores.

BetsAPI no marca un partido como "liga menor/mayor": lo hacemos nosotros
comparando el nombre de la liga contra una lista de palabras clave.
Es una heurística simple y transparente que puedes editar libremente en tu
.env (EXCLUDED_LEAGUE_KEYWORDS) sin tocar código.
"""
from __future__ import annotations


def is_excluded_league(league_name: str | None, excluded_keywords: list[str]) -> bool:
    if not league_name:
        return False
    name = league_name.lower()
    return any(keyword in name for keyword in excluded_keywords)


def extract_league_name(event: dict) -> str:
    league = event.get("league") or {}
    return league.get("name", "") or ""
