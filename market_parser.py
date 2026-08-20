"""
Convierte la respuesta cruda de BetsAPI (Bet365 y Betfair Exchange) en una
lista de "ParsedSelection" homogénea, fácil de comparar entre casas y de
alimentar al OddsTracker.

IMPORTANTE — LEE ESTO ANTES DE PONER EL BOT EN PRODUCCIÓN:
La API de Bet365/Betfair dentro de BetsAPI devuelve una lista PLANA de nodos
(tipo "MG" = grupo de mercado, "MA" = mercado, "PA" = selección con su cuota)
en el orden en que aparecen en el feed. El mapeo exacto de nombres de mercado
puede variar ligeramente según el deporte/torneo. Este parser está construido
según la documentación pública y el ejemplo de la FAQ de BetsAPI, pero
**debes validarlo contra un payload real de tu cuenta** antes de confiar en
las alertas. Para eso incluyo la función `debug_dump(raw)` al final: úsala una
vez con `python -c "..."` sobre una respuesta real y ajusta las palabras clave
de `classify_market()` si tu feed usa nombres distintos.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# --- Conversión de cuotas fraccionarias (Bet365 usa "3/1") a decimales ---

def fractional_to_decimal(odd: str | float) -> float | None:
    if odd is None:
        return None
    if isinstance(odd, (int, float)):
        return float(odd)
    odd = str(odd).strip()
    if not odd:
        return None
    if "/" in odd:
        try:
            num, den = odd.split("/")
            return 1.0 + (float(num) / float(den))
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return float(odd)
    except ValueError:
        return None


LINE_REGEX = re.compile(r"(-?\d+(?:\.\d+)?)")


def extract_line(name: str) -> float | None:
    """Extrae el número de línea de nombres tipo 'Over 2.5', 'Home -1.5', 'Total Under 3'."""
    match = LINE_REGEX.search(name.replace(",", "."))
    return float(match.group(1)) if match else None


@dataclass
class ParsedSelection:
    market_key: str        # ej. "ou_ft", "1x2_ft", "dnb_ht", "handicap_ft"
    market_label: str      # nombre legible para el mensaje de Telegram
    selection: str         # "over", "under", "home", "draw", "away"
    line: float | None     # línea numérica (None para 1X2 / DNB)
    odds: float | None     # cuota decimal
    suspended: bool


MARKET_RULES: list[tuple[str, str, bool, bool]] = [
    # (palabra_clave_en_nombre_grupo, market_key_base, es_over_under, es_handicap)
    ("goals over/under", "ou", True, False),
    ("total goals", "ou", True, False),
    ("draw no bet", "dnb", False, False),
    ("handicap", "handicap", False, True),
    ("fulltime result", "1x2", False, False),
    ("match odds", "1x2", False, False),
    ("full time result", "1x2", False, False),
]


def classify_market(group_name: str) -> tuple[str, str] | None:
    """Devuelve (market_key, etiqueta_legible) o None si no nos interesa este grupo."""
    lowered = group_name.lower()
    is_ht = "1st half" in lowered or "half time" in lowered or "1° half" in lowered

    for keyword, base_key, _is_ou, _is_hcp in MARKET_RULES:
        if keyword in lowered:
            suffix = "ht" if is_ht else "ft"
            key = f"{base_key}_{suffix}"
            period_label = "1ª Parte" if is_ht else "Partido completo"
            label = f"{group_name.strip()} ({period_label})"
            return key, label
    return None


def parse_bet365_event(raw: dict) -> list[ParsedSelection]:
    """
    Recorre la lista plana de nodos que devuelve /v1/bet365/event y produce
    selecciones normalizadas para los mercados que nos interesan.
    """
    results: list[ParsedSelection] = []
    nodes = raw.get("sports", {}) if isinstance(raw.get("sports"), dict) else raw
    flat_nodes = _flatten_nodes(raw)

    current_group_classification: tuple[str, str] | None = None

    for node in flat_nodes:
        node_type = node.get("type")

        if node_type == "MG":
            group_name = node.get("NA", "")
            current_group_classification = classify_market(group_name)
            continue

        if node_type == "PA" and current_group_classification is not None:
            market_key, market_label = current_group_classification
            name = node.get("NA", "")
            odds = fractional_to_decimal(node.get("OD"))
            suspended = str(node.get("SU", "0")) == "1"

            selection, line = _classify_selection(name, market_key)
            if selection is None:
                continue

            results.append(
                ParsedSelection(
                    market_key=market_key,
                    market_label=market_label,
                    selection=selection,
                    line=line,
                    odds=odds,
                    suspended=suspended,
                )
            )

    return results


def parse_betfair_ex_event(raw: dict) -> list[ParsedSelection]:
    """
    Igual que parse_bet365_event pero para /v1/betfair/ex/event.

    NOTA: BetsAPI documenta este endpoint de forma menos detallada que el de
    Bet365. Se asume una estructura equivalente (MG/MA/PA). Si tu cuenta
    devuelve un formato distinto (por ejemplo runners con "back"/"lay" en vez
    de "OD"), ajusta esta función: usa `debug_dump(raw)` para inspeccionar un
    payload real y adapta la extracción de la cuota (para Exchange, se
    recomienda usar el mejor precio "back" disponible como cuota de referencia).
    """
    results: list[ParsedSelection] = []
    flat_nodes = _flatten_nodes(raw)
    current_group_classification: tuple[str, str] | None = None

    for node in flat_nodes:
        node_type = node.get("type")

        if node_type == "MG":
            current_group_classification = classify_market(node.get("NA", ""))
            continue

        if node_type == "PA" and current_group_classification is not None:
            market_key, market_label = current_group_classification
            name = node.get("NA", "")
            # Exchange: preferimos el mejor precio "back" si viene separado;
            # si no, caemos a "OD" como en Bet365.
            odds_raw = node.get("back") or node.get("BACK") or node.get("OD")
            odds = fractional_to_decimal(odds_raw)
            suspended = str(node.get("SU", "0")) == "1"

            selection, line = _classify_selection(name, market_key)
            if selection is None:
                continue

            results.append(
                ParsedSelection(
                    market_key=market_key,
                    market_label=market_label,
                    selection=selection,
                    line=line,
                    odds=odds,
                    suspended=suspended,
                )
            )

    return results


def _classify_selection(name: str, market_key: str) -> tuple[str | None, float | None]:
    lowered = name.lower()
    if market_key.startswith("ou"):
        line = extract_line(name)
        if "over" in lowered:
            return "over", line
        if "under" in lowered:
            return "under", line
        return None, None

    if market_key.startswith("handicap"):
        line = extract_line(name)
        if "home" in lowered or lowered.strip() == "1":
            return "home", line
        if "away" in lowered or lowered.strip() == "2":
            return "away", line
        return None, None

    if market_key.startswith("1x2") or market_key.startswith("dnb"):
        if "draw" in lowered or lowered.strip() == "x":
            return "draw", None
        if "home" in lowered or lowered.strip() == "1":
            return "home", None
        if "away" in lowered or lowered.strip() == "2":
            return "away", None
        return None, None

    return None, None


def _flatten_nodes(raw: dict) -> list[dict]:
    """
    Aplana cualquier estructura anidada tipo lista/dict en una única lista de
    nodos con clave "type", que es como la documentación de BetsAPI describe
    el feed de mercados de Bet365/Betfair.
    """
    flat: list[dict] = []

    def _walk(node):
        if isinstance(node, dict):
            if "type" in node:
                flat.append(node)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(raw)
    return flat


def pick_main_ou_line(selections: list[ParsedSelection], market_key: str) -> float | None:
    """
    Heurística para identificar la línea "principal" de Over/Under: la que
    tiene la cuota Over más cercana a 2.00 (la más equilibrada). Sirve para
    detectar cuando la casa desplaza toda la línea (ej. de 2.5 a 3.0).
    """
    candidates = [
        s for s in selections
        if s.market_key == market_key and s.selection == "over" and s.odds and s.line is not None and not s.suspended
    ]
    if not candidates:
        return None
    best = min(candidates, key=lambda s: abs(s.odds - 2.0))
    return best.line


def debug_dump(raw: dict) -> None:
    """Utilidad manual: imprime los nodos MG/MA/PA para inspeccionar un payload real."""
    for node in _flatten_nodes(raw):
        print(node)
