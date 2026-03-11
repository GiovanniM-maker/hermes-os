"""
HERMES OS — Bot Router
Smistamento messaggi in entrata ai canali separati.
Per ora tutto passa dal Master Bot.
I canali dedicati verranno attivati quando i token saranno disponibili.
"""

import logging

import config

logger = logging.getLogger("hermes.router")


async def send_to_channel(channel: str, message: str, bot=None):
    """
    Invia un messaggio a un canale Telegram specifico.

    Args:
        channel: "ads" | "mail" | "tasks" | "build"
        message: Testo del messaggio
        bot: Istanza Bot Telegram (opzionale, fallback al master)
    """
    token_map = {
        "ads": config.TELEGRAM_ADS_TOKEN,
        "mail": config.TELEGRAM_MAIL_TOKEN,
        "tasks": config.TELEGRAM_TASKS_TOKEN,
        "build": config.TELEGRAM_BUILD_TOKEN,
    }

    token = token_map.get(channel)

    if not token:
        # Fallback: manda sul master bot a Juan direttamente
        if bot and config.TELEGRAM_CHAT_ID:
            prefix = {
                "ads": "\U0001f4ca",
                "mail": "\U0001f4e7",
                "tasks": "\U0001f4cb",
                "build": "\u2699\ufe0f",
            }.get(channel, "\U0001f916")

            await bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=f"{prefix} [{channel.upper()}]\n{message}",
            )
            logger.debug(f"Messaggio inviato via master bot (canale {channel} non configurato)")
        else:
            logger.warning(f"Canale {channel} non configurato e nessun fallback disponibile")
        return

    # Quando i canali saranno configurati, invia con bot dedicato
    from telegram import Bot
    channel_bot = Bot(token=token)
    try:
        await channel_bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,  # Per ora manda a Juan
            text=message,
        )
        logger.info(f"Messaggio inviato su canale {channel}")
    except Exception as e:
        logger.error(f"Errore invio canale {channel}: {e}")
