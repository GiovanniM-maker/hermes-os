"""
HERMES OS — Gmail API Client
Accesso diretto a Gmail via OAuth2 refresh token.
Nessuna dipendenza da n8n per le operazioni email base.
"""

import base64
import logging
from datetime import datetime
from email.mime.text import MIMEText

import httpx

import config

logger = logging.getLogger("hermes.gmail")

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GMAIL_API = "https://gmail.googleapis.com/gmail/v1"

# Token cache
_cached_token: str = ""
_token_expires: float = 0


async def _get_access_token() -> str:
    """Ottieni access token usando il refresh token."""
    global _cached_token, _token_expires

    now = datetime.now().timestamp()
    if _cached_token and now < _token_expires:
        return _cached_token

    if not all([config.GMAIL_CLIENT_ID, config.GMAIL_CLIENT_SECRET, config.GMAIL_REFRESH_TOKEN]):
        raise ValueError(
            "Gmail credentials non configurate. "
            "Servono: GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN"
        )

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(_TOKEN_URL, data={
            "client_id": config.GMAIL_CLIENT_ID,
            "client_secret": config.GMAIL_CLIENT_SECRET,
            "refresh_token": config.GMAIL_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        })
        data = resp.json()

    if "access_token" not in data:
        raise ValueError(f"Gmail token refresh failed: {data.get('error_description', data)}")

    _cached_token = data["access_token"]
    _token_expires = now + data.get("expires_in", 3600) - 60
    logger.info("Gmail: access token rinnovato")
    return _cached_token


async def fetch_unread_emails(max_results: int = 20) -> list[dict]:
    """Fetch email non lette direttamente da Gmail API."""
    token = await _get_access_token()
    auth = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30) as client:
        # 1. Lista messaggi non letti
        resp = await client.get(
            f"{_GMAIL_API}/users/me/messages",
            headers=auth,
            params={"q": "is:unread", "maxResults": max_results},
        )
        resp.raise_for_status()
        messages = resp.json().get("messages", [])

        if not messages:
            return []

        # 2. Dettagli di ogni messaggio
        emails = []
        for i, msg in enumerate(messages):
            resp = await client.get(
                f"{_GMAIL_API}/users/me/messages/{msg['id']}",
                headers=auth,
                params={
                    "format": "metadata",
                    "metadataHeaders": ["From", "Subject", "Date"],
                },
            )
            resp.raise_for_status()
            detail = resp.json()

            hdrs = {
                h["name"]: h["value"]
                for h in detail.get("payload", {}).get("headers", [])
            }

            emails.append({
                "index": i + 1,
                "id": detail.get("id", ""),
                "from": hdrs.get("From", ""),
                "subject": hdrs.get("Subject", "(nessun oggetto)"),
                "snippet": detail.get("snippet", "")[:300],
                "date": hdrs.get("Date", ""),
                "labels": detail.get("labelIds", []),
            })

    logger.info(f"Gmail: {len(emails)} email non lette fetchate")
    return emails


async def archive_email(message_id: str) -> bool:
    """Archivia email (rimuovi INBOX + UNREAD)."""
    token = await _get_access_token()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{_GMAIL_API}/users/me/messages/{message_id}/modify",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"removeLabelIds": ["INBOX", "UNREAD"]},
        )
        ok = resp.status_code == 200
        if ok:
            logger.info(f"Gmail: email {message_id} archiviata")
        else:
            logger.error(f"Gmail: errore archiviazione {message_id}: {resp.status_code}")
        return ok


async def send_email(to: str, subject: str, body: str) -> bool:
    """Invia email via Gmail API."""
    token = await _get_access_token()

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{_GMAIL_API}/users/me/messages/send",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"raw": raw},
        )
        ok = resp.status_code == 200
        if ok:
            logger.info(f"Gmail: email inviata a {to}")
        else:
            logger.error(f"Gmail: errore invio a {to}: {resp.status_code} {resp.text[:200]}")
        return ok
