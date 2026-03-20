"""
HERMES OS — Entry Point
FastAPI app + Telegram multi-bot webhooks + APScheduler
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import config
from bot.master import (
    handle_start,
    handle_message,
    handle_callback,
    handle_voice,
)
from bot.channel_bots import build_channel_bot, get_all_channel_names

# ─── Logging ─────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("hermes")

# ─── Scheduler ───────────────────────────────────────────
scheduler = AsyncIOScheduler()

# ─── Bot Registry ────────────────────────────────────────
# Maps webhook path suffix → Application
bot_registry: dict[str, Application] = {}


def build_master_app() -> Application | None:
    """Build the Master Telegram bot."""
    token = config.TELEGRAM_MASTER_TOKEN
    if not token:
        logger.warning("TELEGRAM_MASTER_TOKEN non configurato — bot disabilitato")
        return None

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_start))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    return app


def setup_scheduled_jobs():
    """Configure recurring jobs — timezone Europe/Rome."""
    from agents.task_bot.orchestrator import scheduled_morning_brief, scheduled_evening_program
    from agents.mail_mind.orchestrator import scheduled_morning_digest

    tz = "Europe/Rome"

    # TaskBot — Brief mattutino ore 08:30 (ora italiana)
    scheduler.add_job(
        scheduled_morning_brief,
        CronTrigger(hour=8, minute=30, timezone=tz),
        id="taskbot_morning", replace_existing=True,
    )
    logger.info("Scheduled: TaskBot brief mattutino @ 08:30 Europe/Rome")

    # MailMind — Digest mattutino ore 09:00 (ora italiana)
    scheduler.add_job(
        scheduled_morning_digest,
        CronTrigger(hour=9, minute=0, timezone=tz),
        id="mailmind_digest", replace_existing=True,
    )
    logger.info("Scheduled: MailMind digest @ 09:00 Europe/Rome")

    # TaskBot — Programma serale ore 21:00 (ora italiana)
    scheduler.add_job(
        scheduled_evening_program,
        CronTrigger(hour=21, minute=0, timezone=tz),
        id="taskbot_evening", replace_existing=True,
    )
    logger.info("Scheduled: TaskBot programma serale @ 21:00 Europe/Rome")


# ─── FastAPI Lifespan ────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("HERMES OS starting up...")

    render_url = os.environ.get("RENDER_EXTERNAL_URL", "")

    # 1. Master bot
    master = build_master_app()
    if master:
        await master.initialize()
        await master.start()
        bot_registry["master"] = master

        if render_url:
            webhook_url = f"{render_url}/webhook/master"
            await master.bot.set_webhook(url=webhook_url)
            logger.info(f"Master webhook: {webhook_url}")

    # 2. Channel bots
    for name in get_all_channel_names():
        bot_app = build_channel_bot(name)
        if bot_app:
            await bot_app.initialize()
            await bot_app.start()
            bot_registry[name] = bot_app

            if render_url:
                webhook_url = f"{render_url}/webhook/{name}"
                await bot_app.bot.set_webhook(url=webhook_url)
                logger.info(f"{name} webhook: {webhook_url}")

    logger.info(f"Bot attivi: {list(bot_registry.keys())}")

    # 3. Scheduler
    setup_scheduled_jobs()
    scheduler.start()
    logger.info("APScheduler avviato")

    yield  # ← App running

    # Shutdown
    logger.info("HERMES OS shutting down...")
    scheduler.shutdown(wait=False)
    for name, bot_app in bot_registry.items():
        await bot_app.stop()
        await bot_app.shutdown()
        logger.info(f"Bot '{name}' spento")


# ─── FastAPI App ─────────────────────────────────────────
app = FastAPI(
    title="HERMES OS",
    description="Sistema AI Personale Autonomo",
    version="1.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Health check per Render."""
    return {
        "status": "ok",
        "system": "HERMES OS",
        "version": "1.1.0",
        "active_bots": list(bot_registry.keys()),
        "scheduler_running": scheduler.running if scheduler else False,
    }


# ─── Trigger Endpoints (per cron esterno / keep-alive) ────

@app.post("/trigger/digest")
async def trigger_digest():
    """Trigger manuale digest email — usabile da cron esterno (es. cron-job.org)."""
    from agents.mail_mind.orchestrator import scheduled_morning_digest
    asyncio.create_task(scheduled_morning_digest())
    logger.info("Trigger manuale: MailMind digest")
    return {"status": "triggered", "job": "mailmind_digest"}


@app.post("/trigger/brief")
async def trigger_brief():
    """Trigger manuale brief mattutino — usabile da cron esterno."""
    from agents.task_bot.orchestrator import scheduled_morning_brief
    asyncio.create_task(scheduled_morning_brief())
    logger.info("Trigger manuale: TaskBot brief")
    return {"status": "triggered", "job": "taskbot_brief"}


@app.post("/trigger/evening")
async def trigger_evening():
    """Trigger manuale programma serale — usabile da cron esterno."""
    from agents.task_bot.orchestrator import scheduled_evening_program
    asyncio.create_task(scheduled_evening_program())
    logger.info("Trigger manuale: TaskBot programma serale")
    return {"status": "triggered", "job": "taskbot_evening"}


@app.get("/keepalive")
async def keepalive():
    """Endpoint keep-alive per impedire a Render free tier di dormire."""
    return {"status": "awake"}


@app.get("/config-check")
async def config_check():
    """Diagnostica: mostra quali env vars sono configurate (senza valori)."""
    from core import gcal_client as gc
    return {
        "telegram_master_token": bool(config.TELEGRAM_MASTER_TOKEN),
        "telegram_chat_id": bool(config.TELEGRAM_CHAT_ID),
        "telegram_chat_id_value": config.TELEGRAM_CHAT_ID[:4] + "..." if config.TELEGRAM_CHAT_ID else "",
        "openrouter_api_key": bool(config.OPENROUTER_API_KEY),
        "gmail_client_id": bool(config.GMAIL_CLIENT_ID),
        "gmail_client_secret": bool(config.GMAIL_CLIENT_SECRET),
        "gmail_refresh_token": bool(config.GMAIL_REFRESH_TOKEN),
        "gcal_configured": gc.is_configured(),
        "n8n_base_url": bool(config.N8N_BASE_URL),
        "n8n_api_key": bool(config.N8N_API_KEY),
        "groq_api_key": bool(config.GROQ_API_KEY),
        "google_drive_folder": bool(config.HERMES_DRIVE_FOLDER_ID),
    }


# ─── Telegram Webhooks ────────────────────────────────────

@app.post("/webhook/{bot_name}")
async def telegram_webhook(bot_name: str, request: Request):
    """Riceve update da Telegram via webhook — routing per bot name."""
    # Retrocompatibilità: /webhook/telegram → master
    effective_name = "master" if bot_name == "telegram" else bot_name

    bot_app = bot_registry.get(effective_name)
    if not bot_app:
        return Response(status_code=404, content=f"Bot '{effective_name}' non trovato")

    data = await request.json()
    update = Update.de_json(data, bot_app.bot)

    # Process in background — return 200 immediately to prevent Telegram retries
    asyncio.create_task(bot_app.process_update(update))
    return Response(status_code=200)
