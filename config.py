"""
HERMES OS — Configurazione Centrale
Tutte le variabili d'ambiente con fallback a os.environ.
"""

import os
import json
import base64

# ─── Telegram ────────────────────────────────────────────
TELEGRAM_MASTER_TOKEN = os.environ.get("TELEGRAM_MASTER_TOKEN", "")
TELEGRAM_PIPELINE_TOKEN = os.environ.get("TELEGRAM_PIPELINE_TOKEN", "")
TELEGRAM_MAIL_TOKEN = os.environ.get("TELEGRAM_MAIL_TOKEN", "")
TELEGRAM_TASKS_TOKEN = os.environ.get("TELEGRAM_TASKS_TOKEN", "")
TELEGRAM_BUILD_TOKEN = os.environ.get("TELEGRAM_BUILD_TOKEN", "")
TELEGRAM_ADS_TOKEN = os.environ.get("TELEGRAM_ADS_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ─── LLM — OpenRouter (gateway unico per Claude + Gemini) ──
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Modelli disponibili via OpenRouter
LLM_MODEL_HEAVY = os.environ.get("LLM_MODEL_HEAVY", "anthropic/claude-sonnet-4")
LLM_MODEL_MEDIUM = os.environ.get("LLM_MODEL_MEDIUM", "google/gemini-2.5-pro")
LLM_MODEL_LIGHT = os.environ.get("LLM_MODEL_LIGHT", "google/gemini-2.5-flash")

# ─── Google Drive (Knowledge Base) ───────────────────────
HERMES_DRIVE_FOLDER_ID = os.environ.get("HERMES_DRIVE_FOLDER_ID", "")

# Service account credentials: JSON diretto o base64-encoded
_drive_creds_raw = os.environ.get("GOOGLE_DRIVE_CREDENTIALS", "")


def get_drive_credentials() -> dict | None:
    """Parse service account credentials from env var (JSON or base64)."""
    if not _drive_creds_raw:
        return None
    try:
        return json.loads(_drive_creds_raw)
    except json.JSONDecodeError:
        try:
            decoded = base64.b64decode(_drive_creds_raw).decode("utf-8")
            return json.loads(decoded)
        except Exception:
            return None


# ─── n8n (PipelineForge) ─────────────────────────────────
N8N_BASE_URL = os.environ.get("N8N_BASE_URL", "")
N8N_API_KEY = os.environ.get("N8N_API_KEY", "")

# ─── Gmail (MailMind) + Google Calendar (TaskBot) ────────
GMAIL_CLIENT_ID = os.environ.get("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "")
GMAIL_REFRESH_TOKEN = os.environ.get("GMAIL_REFRESH_TOKEN", "")
# Calendar: se non specificato, usa lo stesso refresh token di Gmail
GCAL_REFRESH_TOKEN = os.environ.get("GCAL_REFRESH_TOKEN", "")
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary")

# ─── Groq / Whisper (trascrizione audio) ─────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
WHISPER_MODEL = "whisper-large-v3"

# ─── Google Ads (AdsWatch — fase futura) ─────────────────
GOOGLE_ADS_DEVELOPER_TOKEN = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN", "")
GOOGLE_ADS_CLIENT_ID = os.environ.get("GOOGLE_ADS_CLIENT_ID", "")
GOOGLE_ADS_CLIENT_SECRET = os.environ.get("GOOGLE_ADS_CLIENT_SECRET", "")
GOOGLE_ADS_REFRESH_TOKEN = os.environ.get("GOOGLE_ADS_REFRESH_TOKEN", "")

# ─── Meta Marketing API (AdsWatch — fase futura) ─────────
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")

# ─── Parametri Sistema ───────────────────────────────────
MAX_QUESTION_ROUNDS = 3          # Max round domande per task
MAX_QUESTIONS_PER_ROUND = 5      # Max domande in 1 messaggio
QUESTION_TIMEOUT_MINUTES = 30    # Timeout attesa risposta Juan
MAX_DEBUG_ITERATIONS = 5         # Max loop debug/correzione
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
