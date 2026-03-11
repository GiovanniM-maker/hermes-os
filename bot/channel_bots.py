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
from core.transcriber import transcribe_voice
from core.question_engine import receive_answer, has_pending_questions
from core import memory
from bot.telegram_utils import send_long_message

logger = logging.getLogger("hermes.channel_bots")


# ─── Voice handler generico per channel bots ─────────────

def _make_voice_handler(message_handler):
    """Crea un voice handler che trascrive e poi chiama il message handler del bot."""
    async def _voice(update: Update, context):
        if not update.message:
            return
        if str(update.message.chat_id) != config.TELEGRAM_CHAT_ID:
            await update.message.reply_text("\u26d4 Non autorizzato.")
            return

        await update.message.reply_text("\U0001f3a4 Trascrivo il vocale...")

        try:
            voice = update.message.voice or update.message.audio
            if not voice:
                await update.message.reply_text("\u26a0\ufe0f Nessun audio trovato.")
                return

            tg_file = await context.bot.get_file(voice.file_id)
            audio_bytes = await tg_file.download_as_bytearray()
            text = await transcribe_voice(bytes(audio_bytes))

            if not text:
                await update.message.reply_text("\u26a0\ufe0f Non sono riuscito a trascrivere il vocale.")
                return

            await update.message.reply_text(f"\U0001f4dd Trascrizione:\n\u00ab{text}\u00bb")

            # Chiama direttamente l'orchestrator del bot, bypassando il message handler
            # che controlla update.message.text (qui è None perché è un vocale)
            from telegram.ext import ContextTypes
            # Simuliamo la logica del message handler senza dipendere da .text
            await _process_voice_text(text, update, context, message_handler)

        except Exception as e:
            logger.error(f"Errore trascrizione vocale (channel): {e}")
            await update.message.reply_text(f"\u26a0\ufe0f Errore trascrizione: {str(e)[:200]}")

    return _voice


async def _process_voice_text(text: str, update: Update, context, message_handler_name: str):
    """Processa testo da vocale per il channel bot corretto."""
    bot = context.bot

    if message_handler_name == "pipeline":
        from agents.pipeline_forge.orchestrator import handle_request
        memory.add_message("user", f"[PipelineForge] {text}")
        await update.message.reply_text("\u2699\ufe0f Analizzo la richiesta pipeline...")
        try:
            response = await handle_request(text, bot)
        except Exception as e:
            response = f"\u26a0\ufe0f Errore PipelineForge: {str(e)[:300]}"

    elif message_handler_name == "mail":
        from agents.mail_mind.orchestrator import handle_request
        memory.add_message("user", f"[MailMind] {text}")
        try:
            response = await handle_request(text, bot)
        except Exception as e:
            response = f"\u26a0\ufe0f Errore MailMind: {str(e)[:300]}"

    elif message_handler_name == "tasks":
        from agents.task_bot.orchestrator import handle_request
        memory.add_message("user", f"[TaskBot] {text}")
        try:
            response = await handle_request(text, bot)
        except Exception as e:
            response = f"\u26a0\ufe0f Errore TaskBot: {str(e)[:300]}"

    elif message_handler_name == "build":
        from agents.code_forge.orchestrator import handle_request
        memory.add_message("user", f"[CodeForge] {text}")
        await update.message.reply_text("\U0001f4bb Genero il codice...")
        try:
            response = await handle_request(text, bot)
        except Exception as e:
            response = f"\u26a0\ufe0f Errore CodeForge: {str(e)[:300]}"

    else:
        response = "\u26a0\ufe0f Bot non riconosciuto."

    memory.add_message("assistant", response)
    await send_long_message(update, response)


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

    user_text = update.message.text.strip()

    # Se c'è una domanda pending, la risposta va al Question Engine
    if has_pending_questions():
        if receive_answer(user_text):
            await update.message.reply_text("\u2705 Risposta ricevuta! Procedo...")
            return

    from agents.pipeline_forge.orchestrator import handle_request
    memory.add_message("user", f"[PipelineForge] {user_text}")

    await update.message.reply_text("\u2699\ufe0f Analizzo la richiesta pipeline...")
    try:
        response = await handle_request(user_text, context.bot)
    except Exception as e:
        response = f"\u26a0\ufe0f Errore PipelineForge: {str(e)[:300]}"

    memory.add_message("assistant", response)
    await send_long_message(update, response)


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

    user_text = update.message.text.strip()

    if has_pending_questions():
        if receive_answer(user_text):
            await update.message.reply_text("\u2705 Risposta ricevuta! Procedo...")
            return

    from agents.mail_mind.orchestrator import handle_request
    memory.add_message("user", f"[MailMind] {user_text}")

    try:
        response = await handle_request(user_text, context.bot)
    except Exception as e:
        response = f"\u26a0\ufe0f Errore MailMind: {str(e)[:300]}"

    memory.add_message("assistant", response)
    await send_long_message(update, response)


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

    user_text = update.message.text.strip()

    if has_pending_questions():
        if receive_answer(user_text):
            await update.message.reply_text("\u2705 Risposta ricevuta! Procedo...")
            return

    from agents.task_bot.orchestrator import handle_request
    memory.add_message("user", f"[TaskBot] {user_text}")

    try:
        response = await handle_request(user_text, context.bot)
    except Exception as e:
        response = f"\u26a0\ufe0f Errore TaskBot: {str(e)[:300]}"

    memory.add_message("assistant", response)
    await send_long_message(update, response)


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

    user_text = update.message.text.strip()

    if has_pending_questions():
        if receive_answer(user_text):
            await update.message.reply_text("\u2705 Risposta ricevuta! Procedo...")
            return

    from agents.code_forge.orchestrator import handle_request
    memory.add_message("user", f"[CodeForge] {user_text}")

    await update.message.reply_text("\U0001f4bb Genero il codice...")
    try:
        response = await handle_request(user_text, context.bot)
    except Exception as e:
        response = f"\u26a0\ufe0f Errore CodeForge: {str(e)[:300]}"

    memory.add_message("assistant", response)
    await send_long_message(update, response)


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
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, _make_voice_handler(name)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cfg["message"]))

    logger.info(f"Channel bot '{name}' creato (con voice)")
    return app


def get_all_channel_names() -> list[str]:
    """Lista nomi bot canale disponibili."""
    return list(_BOT_CONFIG.keys())
