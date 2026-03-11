"""
HERMES OS — Entry Point
FastAPI app + Telegram webhook + APScheduler
"""

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

import config
from bot.master import (
    handle_start,
    handle_message,
    handle_callback,
    handle_voice,
)

# ─── Logging ─────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("hermes")

# ─── Scheduler ───────────────────────────────────────────
scheduler = AsyncIOScheduler()

# ─── Telegram Application ────────────────────────────────
telegram_app: Application | None = None


def build_telegram_app() -> Application | None:
    """Build the Telegram bot application."""
    token = config.TELEGRAM_MASTER_TOKEN
    if not token:
        logger.warning("TELEGRAM_MASTER_TOKEN non configurato — bot disabilitato")
        return None

    app = Application.builder().token(token).build()

    # Handlers
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_start))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    return app


def setup_scheduled_jobs():
    """Configure recurring jobs (AdsWatch, MailMind, TaskBot)."""
    # TaskBot — Brief mattutino ore 08:30
    # scheduler.add_job(
    #     task_bot_morning_brief,
    #     "cron", hour=8, minute=30,
    #     id="taskbot_morning", replace_existing=True,
    # )

    # MailMind — Digest serale ore 19:00
    # scheduler.add_job(
    #     mailmind_evening_digest,
    #     "cron", hour=19, minute=0,
    #     id="mailmind_digest", replace_existing=True,
    # )

    # AdsWatch — Check anomalie ogni 6 ore
    # scheduler.add_job(
    #     adswatch_check,
    #     "interval", hours=6,
    #     id="adswatch_check", replace_existing=True,
    # )

    logger.info("Scheduled jobs configurati (attualmente commentati)")


# ─── FastAPI Lifespan ────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    global telegram_app

    logger.info("HERMES OS starting up...")

    # Init Telegram
    telegram_app = build_telegram_app()
    if telegram_app:
        await telegram_app.initialize()
        await telegram_app.start()

        # Set webhook su Render
        render_url = os.environ.get("RENDER_EXTERNAL_URL", "")
        if render_url:
            webhook_url = f"{render_url}/webhook/telegram"
            await telegram_app.bot.set_webhook(url=webhook_url)
            logger.info(f"Webhook Telegram impostato: {webhook_url}")
        else:
            logger.warning("RENDER_EXTERNAL_URL non impostato — webhook non configurato")

    # Init Scheduler
    setup_scheduled_jobs()
    scheduler.start()
    logger.info("APScheduler avviato")

    yield  # ← App running

    # Shutdown
    logger.info("HERMES OS shutting down...")
    scheduler.shutdown(wait=False)
    if telegram_app:
        await telegram_app.stop()
        await telegram_app.shutdown()


# ─── FastAPI App ─────────────────────────────────────────
app = FastAPI(
    title="HERMES OS",
    description="Sistema AI Personale Autonomo",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Health check per Render."""
    return {
        "status": "ok",
        "system": "HERMES OS",
        "version": "1.0.0",
        "telegram_bot": telegram_app is not None,
        "scheduler_running": scheduler.running if scheduler else False,
    }


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """Riceve update da Telegram via webhook."""
    if not telegram_app:
        return Response(status_code=503, content="Bot non inizializzato")

    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return Response(status_code=200)
