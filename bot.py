"""Bot de Telegram (aiogram v3): envío de alertas + comandos básicos de control."""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message

from config import Settings

logger = logging.getLogger("bot")


def build_bot_and_dispatcher(settings: Settings) -> tuple[Bot, Dispatcher]:
    bot = Bot(token=settings.telegram_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    @dp.message(Command("start"))
    async def start_handler(message: Message) -> None:
        await message.answer(
            "🤖 Bot de alertas de mercado en marcha.\n"
            "Monitorizo movimientos de cuota/línea en ligas menores de fútbol "
            "(Bet365 vs Betfair Exchange) y aviso aquí cuando detecto entrada "
            "fuerte de dinero.\nUsa /status para ver la configuración actual."
        )

    @dp.message(Command("status"))
    async def status_handler(message: Message) -> None:
        await message.answer(
            "📊 <b>Configuración actual</b>\n"
            f"Intervalo de sondeo: {settings.poll_interval_seconds}s\n"
            f"Umbral movimiento de cuota: {settings.min_odds_change_pct}%\n"
            f"Ventana de análisis: {settings.odds_move_window_seconds}s\n"
            f"Diferencia mínima de línea: {settings.min_line_diff}\n"
            f"Cooldown por alerta: {settings.alert_cooldown_minutes} min\n"
            f"Ligas excluidas: {len(settings.excluded_league_keywords)} palabras clave"
        )

    return bot, dp


async def send_alert_factory(bot: Bot, chat_id: str):
    async def _send(text: str) -> None:
        try:
            await bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=True)
        except Exception:
            logger.exception("No se pudo enviar la alerta a Telegram")

    return _send
