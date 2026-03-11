"""
HERMES OS — Entry Point
FastAPI app + Telegram multi-bot webhooks + APScheduler
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
    """Configure recurring jobs."""
    from agents.task_bot.orchestrator import scheduled_morning_brief
    from agents.mail_mind.orchestrator import scheduled_morning_digest

    # TaskBot — Brief mattutino ore 08:30
    scheduler.add_job(
        scheduled_morning_brief, "cron", hour=8, minute=30,
        id="taskbot_morning", replace_existing=True,
    )
    logger.info("Scheduled: TaskBot brief mattutino @ 08:30")

    # MailMind — Digest mattutino ore 09:00
    scheduler.add_job(
        scheduled_morning_digest, "cron", hour=9, minute=0,
        id="mailmind_digest", replace_existing=True,
    )
    logger.info("Scheduled: MailMind digest @ 09:00")


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
    await bot_app.process_update(update)
    return Response(status_code=200)
