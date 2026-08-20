"""
Punto de entrada. Arranca:
  - El polling de comandos de Telegram (/start, /status) en segundo plano.
  - El bucle de monitoreo de BetsAPI (asyncio.create_task), que no bloquea
    al bot y consulta la API cada POLL_INTERVAL_SECONDS.
"""
from __future__ import annotations

import asyncio
import logging
import signal

from bot import build_bot_and_dispatcher, send_alert_factory
from config import settings
from monitor import Monitor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("main")


async def main() -> None:
    bot, dp = build_bot_and_dispatcher(settings)
    send_alert = await send_alert_factory(bot, settings.telegram_chat_id)

    monitor = Monitor(settings, send_alert)

    monitor_task = asyncio.create_task(monitor.run_forever(), name="monitor-loop")
    polling_task = asyncio.create_task(dp.start_polling(bot), name="telegram-polling")

    logger.info("Bot arrancado. Intervalo de sondeo: %ss", settings.poll_interval_seconds)

    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Señal de parada recibida, cerrando...")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass  # Windows

    done, pending = await asyncio.wait(
        [monitor_task, polling_task, asyncio.create_task(stop_event.wait())],
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()
    for task in done:
        if task.exception():
            logger.error("Tarea finalizada con error: %s", task.exception())

    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
