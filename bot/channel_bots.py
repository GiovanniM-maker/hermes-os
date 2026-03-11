"""
HERMES OS — Channel Bots
Bot separati per ogni Task Orchestrator.
Ogni bot ha il suo webhook e gestisce direttamente il suo dominio.
"""

import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import config
from core.llm_router import chat, TaskComplexity
from core import memory

logger = logging.getLogger("hermes.channel_bots")


# ─── Pipeline Bot ─────────────────────────────────────────

async def _pipeline_start(update: Update, context):
    await update.message.reply_text(
        "\u2699\ufe0f PipelineForge Bot\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "Descrivi il workflow che vuoi creare e lo costruisco su n8n.\n\n"
        "Esempi:\n"
        "- 'Crea un workflow che legge un Google Sheet e manda email'\n"
        "- 'Automazione: quando arriva un lead, crea task su Notion'\n"
        "- 'Webhook che riceve dati e li salva su Airtable'"
    )


async def _pipeline_message(update: Update, context):
    if not update.message or not update.message.text:
        return
    if str(update.message.chat_id) != config.TELEGRAM_CHAT_ID:
        await update.message.reply_text("\u26d4 Non autorizzato.")
        return

    from agents.pipeline_forge.orchestrator import handle_request
    user_text = update.message.text.strip()
    memory.add_message("user", f"[PipelineForge] {user_text}")

    await update.message.reply_text("\u2699\ufe0f Analizzo la richiesta pipeline...")
    try:
        response = await handle_request(user_text, context.bot)
    except Exception as e:
        response = f"\u26a0\ufe0f Errore PipelineForge: {str(e)[:300]}"

    memory.add_message("assistant", response)
    await update.message.reply_text(response, parse_mode=None)


# ─── Mail Bot ─────────────────────────────────────────────

async def _mail_start(update: Update, context):
    await update.message.reply_text(
        "\U0001f4e7 MailMind Bot\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "Gestisco le tue email via n8n + Gmail.\n\n"
        "Comandi:\n"
        "- 'digest' \u2014 Sommario email non lette\n"
        "- 'rispondi a [email]' \u2014 Genera risposta\n"
        "- 'archivia' \u2014 Archivia email\n"
        "- 'configura mailmind' \u2014 Setup workflow n8n"
    )


async def _mail_message(update: Update, context):
    if not update.message or not update.message.text:
        return
    if str(update.message.chat_id) != config.TELEGRAM_CHAT_ID:
        await update.message.reply_text("\u26d4 Non autorizzato.")
        return

    from agents.mail_mind.orchestrator import handle_request
    user_text = update.message.text.strip()
    memory.add_message("user", f"[MailMind] {user_text}")

    try:
        response = await handle_request(user_text, context.bot)
    except Exception as e:
        response = f"\u26a0\ufe0f Errore MailMind: {str(e)[:300]}"

    memory.add_message("assistant", response)
    await update.message.reply_text(response, parse_mode=None)


# ─── Tasks Bot ────────────────────────────────────────────

async def _tasks_start(update: Update, context):
    await update.message.reply_text(
        "\U0001f4cb TaskBot\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "Gestisco i tuoi task giornalieri.\n\n"
        "Comandi:\n"
        "- 'aggiungi task: [descrizione]' \u2014 Nuovo task\n"
        "- 'tasks' \u2014 Lista task attive\n"
        "- 'fatto 1' \u2014 Completa task #1\n"
        "- 'brief' \u2014 Brief mattutino"
    )


async def _tasks_message(update: Update, context):
    if not update.message or not update.message.text:
        return
    if str(update.message.chat_id) != config.TELEGRAM_CHAT_ID:
        await update.message.reply_text("\u26d4 Non autorizzato.")
        return

    from agents.task_bot.orchestrator import handle_request
    user_text = update.message.text.strip()
    memory.add_message("user", f"[TaskBot] {user_text}")

    try:
        response = await handle_request(user_text, context.bot)
    except Exception as e:
        response = f"\u26a0\ufe0f Errore TaskBot: {str(e)[:300]}"

    memory.add_message("assistant", response)
    await update.message.reply_text(response, parse_mode=None)


# ─── Build Bot (CodeForge) ────────────────────────────────

async def _build_start(update: Update, context):
    await update.message.reply_text(
        "\U0001f4bb CodeForge Bot\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "Genero codice, landing page, script e componenti.\n\n"
        "Esempi:\n"
        "- 'Scrivi uno script Python che scrape prezzi Amazon'\n"
        "- 'Crea una landing page per un corso AI'\n"
        "- 'Genera un componente React per dashboard'"
    )


async def _build_message(update: Update, context):
    if not update.message or not update.message.text:
        return
    if str(update.message.chat_id) != config.TELEGRAM_CHAT_ID:
        await update.message.reply_text("\u26d4 Non autorizzato.")
        return

    from agents.code_forge.orchestrator import handle_request
    user_text = update.message.text.strip()
    memory.add_message("user", f"[CodeForge] {user_text}")

    await update.message.reply_text("\U0001f4bb Genero il codice...")
    try:
        response = await handle_request(user_text, context.bot)
    except Exception as e:
        response = f"\u26a0\ufe0f Errore CodeForge: {str(e)[:300]}"

    memory.add_message("assistant", response)
    await update.message.reply_text(response, parse_mode=None)


# ─── Bot Builders ─────────────────────────────────────────

_BOT_CONFIG = {
    "pipeline": {
        "token_attr": "TELEGRAM_PIPELINE_TOKEN",
        "start": _pipeline_start,
        "message": _pipeline_message,
    },
    "mail": {
        "token_attr": "TELEGRAM_MAIL_TOKEN",
        "start": _mail_start,
        "message": _mail_message,
    },
    "tasks": {
        "token_attr": "TELEGRAM_TASKS_TOKEN",
        "start": _tasks_start,
        "message": _tasks_message,
    },
    "build": {
        "token_attr": "TELEGRAM_BUILD_TOKEN",
        "start": _build_start,
        "message": _build_message,
    },
}


def build_channel_bot(name: str) -> Application | None:
    """Build a channel bot by name. Returns None if token not configured."""
    cfg = _BOT_CONFIG.get(name)
    if not cfg:
        return None

    token = getattr(config, cfg["token_attr"], "")
    if not token:
        logger.info(f"Channel bot '{name}': token non configurato, skip")
        return None

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cfg["start"]))
    app.add_handler(CommandHandler("help", cfg["start"]))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cfg["message"]))

    logger.info(f"Channel bot '{name}' creato")
    return app


def get_all_channel_names() -> list[str]:
    """Lista nomi bot canale disponibili."""
    return list(_BOT_CONFIG.keys())
