"""
HERMES OS — Master Orchestrator
Punto di ingresso di tutto il sistema.
Riceve ogni messaggio da Telegram, decide cosa fare,
smista ai Task Orchestrator corretti.
"""

import json
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import config
from core.llm_router import classify_intent, chat, TaskComplexity
from core.question_engine import receive_answer, has_pending_questions
from core.transcriber import transcribe_voice
from core import memory
from core import knowledge_base as kb

logger = logging.getLogger("hermes.master")


# ─── Handlers ────────────────────────────────────────────

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler per /start e /help."""
    welcome = (
        "\U0001f916 HERMES OS \u2014 Sistema AI Personale\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "Sono il tuo assistente AI autonomo.\n"
        "Puoi chiedermi qualsiasi cosa:\n\n"
        "\u26a1 Creare workflow n8n (PipelineForge)\n"
        "\U0001f4ca Analisi campagne ads (AdsWatch)\n"
        "\U0001f4e7 Gestione email (MailMind)\n"
        "\U0001f4cb Gestione task (TaskBot)\n"
        "\U0001f4bb Generare codice/landing (CodeForge)\n\n"
        "Comandi:\n"
        "/status \u2014 Stato sistema\n"
        "/tasks \u2014 Lista task attive\n"
        "/kb \u2014 Cerca nella Knowledge Base\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "Scrivi qualcosa o manda un vocale \U0001f3a4"
    )
    await update.message.reply_text(welcome)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler principale per messaggi di testo.
    Classifica l'intent e smista al Task Orchestrator corretto.
    """
    if not update.message or not update.message.text:
        return

    user_text = update.message.text.strip()
    chat_id = str(update.message.chat_id)

    # Verifica che il messaggio sia da Juan
    if chat_id != config.TELEGRAM_CHAT_ID:
        logger.warning(f"Messaggio da chat_id non autorizzato: {chat_id}")
        await update.message.reply_text("\u26d4 Non sei autorizzato a usare questo bot.")
        return

    logger.info(f"Messaggio ricevuto: {user_text[:100]}...")
    memory.add_message("user", user_text)

    # Se ci sono domande pending, la risposta va al Question Engine
    if has_pending_questions():
        matched = receive_answer(user_text)
        if matched:
            await update.message.reply_text("\u2705 Risposta ricevuta! Procedo...")
            return

    # Classifica intent
    await update.message.reply_text("\U0001f9e0 Analizzo la richiesta...")

    try:
        intent_result = await classify_intent(user_text)
    except Exception as e:
        logger.error(f"Errore classificazione intent: {e}")
        await update.message.reply_text(
            f"\u26a0\ufe0f Errore nel routing: {str(e)[:200]}\n"
            "Riprova tra qualche secondo."
        )
        return

    intent = intent_result.get("intent", "general_question")
    confidence = intent_result.get("confidence", 0)
    details = intent_result.get("details", "")

    logger.info(f"Intent: {intent} (confidence: {confidence}) — {details}")

    # Routing ai Task Orchestrator
    response = await _route_to_orchestrator(
        intent=intent,
        user_text=user_text,
        confidence=confidence,
        bot=context.bot,
    )

    memory.add_message("assistant", response)
    await update.message.reply_text(response, parse_mode=None)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler per messaggi vocali — trascrizione via Groq Whisper + routing."""
    if not update.message:
        return

    chat_id = str(update.message.chat_id)
    if chat_id != config.TELEGRAM_CHAT_ID:
        await update.message.reply_text("\u26d4 Non sei autorizzato.")
        return

    await update.message.reply_text("\U0001f3a4 Trascrivo il vocale...")

    try:
        # Scarica il file audio da Telegram
        voice = update.message.voice or update.message.audio
        if not voice:
            await update.message.reply_text("\u26a0\ufe0f Nessun audio trovato.")
            return

        tg_file = await context.bot.get_file(voice.file_id)
        audio_bytes = await tg_file.download_as_bytearray()

        # Trascrivi con Groq Whisper
        text = await transcribe_voice(bytes(audio_bytes))

        if not text:
            await update.message.reply_text("\u26a0\ufe0f Non sono riuscito a trascrivere il vocale.")
            return

        # Mostra trascrizione
        await update.message.reply_text(f"\U0001f4dd Trascrizione:\n\u00ab{text}\u00bb")

        # Processa come messaggio di testo normale
        update.message.text = text
        await handle_message(update, context)

    except Exception as e:
        logger.error(f"Errore trascrizione vocale: {e}")
        await update.message.reply_text(f"\u26a0\ufe0f Errore trascrizione: {str(e)[:200]}")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler per callback query (bottoni inline)."""
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = query.data

    logger.info(f"Callback: {data}")

    if data.startswith("task_done:"):
        task_id = data.split(":", 1)[1]
        await query.edit_message_text(f"\u2705 Task {task_id} completata!")
        await memory.log_task_completion(
            task_description=f"Task #{task_id}",
            agent="TaskBot",
            outcome="Completata via Telegram",
        )

    elif data.startswith("task_postpone:"):
        task_id = data.split(":", 1)[1]
        await query.edit_message_text(f"\u23f0 Task {task_id} posticipata a domani")


# ─── Routing ─────────────────────────────────────────────

async def _route_to_orchestrator(
    intent: str,
    user_text: str,
    confidence: float,
    bot=None,
) -> str:
    """Smista al Task Orchestrator corretto in base all'intent."""

    if intent == "pipeline_request":
        return await _handle_pipeline_request(user_text, bot)

    elif intent == "ads_question":
        return (
            "\U0001f4ca AdsWatch \u2014 Coming Soon\n"
            "Il modulo di monitoraggio campagne sar\u00e0 attivato nella prossima fase.\n"
            "Per ora puoi chiedermi analisi generali."
        )

    elif intent == "mail_task":
        from agents.mail_mind.orchestrator import handle_request as mail_handle
        try:
            return await mail_handle(user_text, bot)
        except Exception as e:
            logger.error(f"MailMind error: {e}")
            return f"\u26a0\ufe0f Errore MailMind: {str(e)[:300]}"

    elif intent == "task_mgmt":
        return await _handle_task_request(user_text, bot)

    elif intent == "code_request":
        return await _handle_code_request(user_text, bot)

    elif intent == "complex_project":
        return await _handle_complex_project(user_text, bot)

    elif intent == "system_command":
        return await _handle_system_command(user_text)

    else:
        # general_question — risposta diretta con LLM
        return await _handle_general_question(user_text)


# ─── Orchestrator Handlers ───────────────────────────────

async def _handle_pipeline_request(user_text: str, bot=None) -> str:
    """Smista a PipelineForge."""
    from agents.pipeline_forge.orchestrator import handle_request
    try:
        return await handle_request(user_text, bot)
    except Exception as e:
        logger.error(f"PipelineForge error: {e}")
        return f"\u26a0\ufe0f Errore PipelineForge: {str(e)[:300]}"


async def _handle_task_request(user_text: str, bot=None) -> str:
    """Smista a TaskBot."""
    from agents.task_bot.orchestrator import handle_request
    try:
        return await handle_request(user_text, bot)
    except Exception as e:
        logger.error(f"TaskBot error: {e}")
        return f"\u26a0\ufe0f Errore TaskBot: {str(e)[:300]}"


async def _handle_code_request(user_text: str, bot=None) -> str:
    """Smista a CodeForge."""
    return (
        "\U0001f4bb CodeForge \u2014 Coming Soon\n"
        "Il generatore di codice/landing sar\u00e0 attivato nell'ultima fase di build."
    )


async def _handle_complex_project(user_text: str, bot=None) -> str:
    """Gestisce progetti complessi multi-orchestratore."""
    return (
        "\U0001f680 Progetto Complesso Rilevato\n"
        "La modalit\u00e0 multi-orchestratore sar\u00e0 attivata quando tutti gli agenti saranno online.\n"
        "Per ora posso aiutarti con singoli task."
    )


async def _handle_system_command(user_text: str) -> str:
    """Gestisce comandi di sistema."""
    text_lower = user_text.lower()

    if "status" in text_lower:
        return (
            "\U0001f916 HERMES OS \u2014 Status\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "\u2705 Master Orchestrator: online\n"
            "\u2705 LLM Router: online (OpenRouter)\n"
            "\u2705 Knowledge Base: online (Drive)\n"
            "\u2705 Question Engine: online\n"
            "\u2705 PipelineForge: online\n"
            "\u2705 TaskBot: online\n"
            "\u23f8\ufe0f MailMind: in attesa (Gmail OAuth)\n"
            "\u23f8\ufe0f AdsWatch: in attesa\n"
            "\u23f8\ufe0f CodeForge: in attesa\n"
        )

    return "\U0001f916 Comando di sistema non riconosciuto. Prova /help"


async def _handle_general_question(user_text: str) -> str:
    """Risposta diretta a domande generali usando LLM."""
    # Carica contesto conversazione
    context_messages = memory.get_context(last_n=5)

    system_prompt = (
        "Sei HERMES, assistente AI personale di Juan, un consulente AI/media buyer freelance. "
        "Rispondi in modo diretto, conciso e operativo. "
        "Se la domanda riguarda un cliente specifico o un task, suggerisci il comando appropriato. "
        "Parla in italiano."
    )

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(context_messages)
    messages.append({"role": "user", "content": user_text})

    try:
        response = await chat(
            messages=messages,
            complexity=TaskComplexity.LIGHT,
            temperature=0.5,
            max_tokens=1024,
        )
        return response
    except Exception as e:
        logger.error(f"Errore risposta generale: {e}")
        return f"\u26a0\ufe0f Non riesco a rispondere: {str(e)[:200]}"
