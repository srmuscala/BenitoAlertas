# Bot de alertas de mercado (Bet365 + Betfair Exchange → Telegram)

Bot en Python (aiogram v3 + aiohttp) que monitoriza partidos de fútbol de
**ligas menores** en directo y avisa por Telegram cuando detecta:

1. **Movimiento fuerte de cuota** en Bet365 o Betfair Exchange (1X2, O/U, DNB,
   Hándicap — HT y FT) que **no** coincide con un gol o una tarjeta roja en la
   misma ventana de tiempo → probable entrada fuerte de dinero.
2. **Desplazamiento de la línea principal** (ej. el Over/Under pasa de 2.5 a
   3.0) sin gol/roja de por medio.
3. **Diferencia de línea entre casas** para el mismo partido y mercado (ej.
   Bet365 Over 1.5 vs Betfair Exchange Over 2.25).

## 1. Sobre la API

Uso **BetsAPI** (https://betsapi.com) porque agrega en un mismo formato los
datos de Bet365 y Betfair Exchange (además de otras casas), tiene histórico
desde 2016 y planes desde ~10 USD/mes. **Es de pago**, no gratuita.

Alternativas si buscas algo más barato/gratis, con estructura de cliente casi
idéntica (solo cambiarías las URLs en `betsapi_client.py`):
- **OddsJam** / **Odds-API.io**: cubren Betfair Exchange y odds en vivo, con
  planes de entrada más baratos, pero sin histórico tan largo.
- **The Odds API**: muy barata / con capa gratuita limitada, pero su cobertura
  de Betfair Exchange (lay odds) es más limitada y no siempre cubre ligas muy
  menores.
- **Pinnacle API** (gratuita para su propio feed): no incluye Bet365 ni
  Betfair, solo sirve como referencia de "línea justa".

No existe ninguna API 100% gratuita con la cobertura de Bet365 + Betfair
Exchange en ligas menores que uses aquí; todas las serias son de pago porque
scrapear/replicar ese feed tiene coste de licencia.

## 2. ⚠️ Antes de confiar en las alertas: valida el parser

Bet365 y Betfair Exchange devuelven, dentro de BetsAPI, una lista de nodos
`MG` (grupo de mercado) / `MA` (mercado) / `PA` (selección + cuota). El
mapeo de nombres de mercado en `market_parser.py` está construido según la
documentación pública, pero **puede variar** ligeramente por deporte/torneo.

Antes de dejarlo en producción:
```bash
python - <<'PY'
import asyncio, aiohttp
from betsapi_client import BetsAPIClient
from market_parser import debug_dump

async def main():
    async with aiohttp.ClientSession() as s:
        client = BetsAPIClient(token="TU_TOKEN", session=s)
        raw = await client.get_bet365_event(fi="ALGUN_FI_REAL_EN_VIVO")
        debug_dump(raw)

asyncio.run(main())
PY
```
Así ves los nombres reales de mercado/selección de tu cuenta y ajustas
`classify_market()` / `_classify_selection()` si hace falta. Haz lo mismo con
`get_betfair_ex_event` para Betfair Exchange.

También revisa `get_red_cards()` en `monitor.py`: el conteo de rojas es
"best-effort" y debes verificarlo contra tu payload real (el marcador, que sí
es 100% fiable, ya se usa como filtro principal anti-falsos-positivos).

## 3. Configuración

```bash
cp .env.example .env
# Rellena TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID y BETSAPI_TOKEN
```

- `TELEGRAM_CHAT_ID`: id del canal/grupo (usa @userinfobot o el método
  `getUpdates` para obtenerlo; los IDs de canal suelen empezar por `-100`).
- Ajusta `MIN_ODDS_CHANGE_PCT`, `ODDS_MOVE_WINDOW_SECONDS`, `MIN_LINE_DIFF`
  y `EXCLUDED_LEAGUE_KEYWORDS` a tu gusto sin tocar código.

## 4. Ejecución local (para pruebas)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

## 5. Ponerlo 24/7 sin dejar tu PC encendido

Tienes razón: para que corra todo el día sin gastar batería/energía de tu
ordenador o móvil, necesitas un servidor pequeño en la nube. Opciones,
de más a menos económicas:

1. **Oracle Cloud Free Tier**: incluye una VM ARM "Always Free" con recursos
   de sobra para este bot, sin coste mensual mientras te mantengas dentro del
   tier gratuito. Es la opción recomendada si no quieres pagar hosting.
2. **VPS barato** (Hetzner, Contabo, DigitalOcean, etc.): desde ~4-6 USD/mes,
   1 vCPU y 1 GB RAM sobran de largo.
3. **Railway / Render / Fly.io**: despliegue tipo "Docker sin gestionar
   servidor", con capa gratuita o muy barata para procesos pequeños tipo
   worker (no necesitas puerto HTTP, el bot solo hace peticiones salientes).

### Con Docker (recomendado, funciona igual en cualquier VPS)
```bash
docker compose up -d --build
docker compose logs -f     # ver logs en vivo
```
El contenedor tiene `restart: unless-stopped`, así que si el servidor se
reinicia, el bot vuelve a arrancar solo.

### Sin Docker (systemd, en un VPS Ubuntu/Debian)
```bash
sudo mkdir -p /opt/betting_alert_bot
sudo cp -r . /opt/betting_alert_bot
cd /opt/betting_alert_bot
python3 -m venv venv && venv/bin/pip install -r requirements.txt
sudo useradd -r -s /usr/sbin/nologin botuser || true
sudo chown -R botuser:botuser /opt/betting_alert_bot
sudo cp betting-alert-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now betting-alert-bot
sudo systemctl status betting-alert-bot
journalctl -u betting-alert-bot -f     # ver logs en vivo
```

Con cualquiera de las dos opciones, el bot queda corriendo en la nube 24/7 y
tu ordenador/móvil puede estar apagado; solo recibirás las alertas en
Telegram.

## 6. Estructura del proyecto

```
config.py            # Carga de .env y parámetros ajustables
betsapi_client.py     # Cliente aiohttp con reintentos/backoff (429/500)
league_filter.py      # Exclusión de ligas grandes
market_parser.py      # Bet365/Betfair -> selecciones normalizadas
odds_tracker.py        # Detección de movimientos, desplazamientos y diffs
alert_formatter.py    # Mensajes HTML para Telegram
monitor.py            # Bucle de monitoreo (asyncio.create_task cada X seg)
bot.py                 # aiogram v3: Bot/Dispatcher + /start /status
main.py                 # Punto de entrada
```

## 7. Límites y honestidad técnica

- El "cero falsos positivos por gol/roja/penalti" se basa en comparar el
  marcador (fiable) y un contador de rojas (best-effort, revísalo). No hay
  forma 100% infalible de descartar *todas* las causas "de juego" (por
  ejemplo, una lesión grave también mueve la cuota); esto es una heurística
  razonable, no una garantía absoluta.
- Ajusta `MAX_CONCURRENT_REQUESTS` y `POLL_INTERVAL_SECONDS` al plan de
  BetsAPI que contrates para no chocar con el rate limit (verás avisos 429 en
  los logs si te pasas; el cliente reintenta con backoff exponencial).
- Nada de esto es asesoramiento financiero ni de apuestas; es una herramienta
  de monitorización de datos públicos de mercado.
