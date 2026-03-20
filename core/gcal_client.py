"""
HERMES OS — Google Calendar API Client
Accesso diretto a Google Calendar via OAuth2 refresh token.
Usa le stesse credenziali OAuth di Gmail (client_id, client_secret).
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

import config

logger = logging.getLogger("hermes.gcal")

_TOKEN_URL = "https://oauth2.googleapis.com/token"


def is_configured() -> bool:
    """Check se le credenziali Google Calendar sono presenti."""
    refresh = config.GCAL_REFRESH_TOKEN or config.GMAIL_REFRESH_TOKEN
    return bool(config.GMAIL_CLIENT_ID and config.GMAIL_CLIENT_SECRET and refresh)
_GCAL_API = "https://www.googleapis.com/calendar/v3"
_TZ = ZoneInfo("Europe/Rome")

# Token cache (condiviso con gmail_client se stesse credenziali)
_cached_token: str = ""
_token_expires: float = 0


async def _get_access_token() -> str:
    """Ottieni access token usando il refresh token."""
    global _cached_token, _token_expires

    now = datetime.now().timestamp()
    if _cached_token and now < _token_expires:
        return _cached_token

    client_id = config.GMAIL_CLIENT_ID
    client_secret = config.GMAIL_CLIENT_SECRET
    refresh_token = config.GCAL_REFRESH_TOKEN or config.GMAIL_REFRESH_TOKEN

    if not all([client_id, client_secret, refresh_token]):
        raise ValueError(
            "Google Calendar credentials non configurate. "
            "Servono: GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GCAL_REFRESH_TOKEN (o GMAIL_REFRESH_TOKEN)"
        )

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(_TOKEN_URL, data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
        data = resp.json()

    if "access_token" not in data:
        raise ValueError(f"Google token refresh failed: {data.get('error_description', data)}")

    _cached_token = data["access_token"]
    _token_expires = now + data.get("expires_in", 3600) - 60
    logger.info("GCal: access token rinnovato")
    return _cached_token


def _calendar_id() -> str:
    """ID calendario da usare."""
    return config.GOOGLE_CALENDAR_ID or "primary"


def _to_rfc3339(dt: datetime) -> str:
    """Converte datetime in formato RFC3339 con timezone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TZ)
    return dt.isoformat()


async def list_events(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    max_results: int = 20,
) -> list[dict]:
    """
    Lista eventi dal calendario.
    Default: da adesso a fine giornata se non specificato.
    """
    token = await _get_access_token()
    now = datetime.now(_TZ)

    if date_from is None:
        date_from = now
    if date_to is None:
        date_to = date_from.replace(hour=23, minute=59, second=59)

    params = {
        "timeMin": _to_rfc3339(date_from),
        "timeMax": _to_rfc3339(date_to),
        "maxResults": max_results,
        "singleEvents": "true",
        "orderBy": "startTime",
        "timeZone": "Europe/Rome",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{_GCAL_API}/calendars/{_calendar_id()}/events",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])

    events = []
    for item in items:
        start = item.get("start", {})
        end = item.get("end", {})
        events.append({
            "id": item.get("id", ""),
            "summary": item.get("summary", "(senza titolo)"),
            "start": start.get("dateTime", start.get("date", "")),
            "end": end.get("dateTime", end.get("date", "")),
            "location": item.get("location", ""),
            "description": item.get("description", ""),
            "all_day": "date" in start and "dateTime" not in start,
            "status": item.get("status", "confirmed"),
            "html_link": item.get("htmlLink", ""),
        })

    logger.info(f"GCal: {len(events)} eventi trovati")
    return events


async def get_events_for_date(date: datetime) -> list[dict]:
    """Tutti gli eventi di un giorno specifico."""
    day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = date.replace(hour=23, minute=59, second=59, microsecond=0)
    return await list_events(date_from=day_start, date_to=day_end)


async def get_tomorrow_events() -> list[dict]:
    """Eventi di domani."""
    tomorrow = datetime.now(_TZ) + timedelta(days=1)
    return await get_events_for_date(tomorrow)


async def get_week_events() -> list[dict]:
    """Eventi da oggi a fine settimana (domenica)."""
    now = datetime.now(_TZ)
    days_until_sunday = 6 - now.weekday()
    if days_until_sunday <= 0:
        days_until_sunday = 7
    end_of_week = now + timedelta(days=days_until_sunday)
    return await list_events(
        date_from=now,
        date_to=end_of_week.replace(hour=23, minute=59, second=59),
    )


async def create_event(
    summary: str,
    start: datetime,
    end: datetime,
    description: str = "",
    location: str = "",
) -> dict:
    """
    Crea un evento sul calendario.
    Ritorna l'evento creato con id e link.
    """
    token = await _get_access_token()

    body = {
        "summary": summary,
        "start": {"dateTime": _to_rfc3339(start), "timeZone": "Europe/Rome"},
        "end": {"dateTime": _to_rfc3339(end), "timeZone": "Europe/Rome"},
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{_GCAL_API}/calendars/{_calendar_id()}/events",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        event = resp.json()

    logger.info(f"GCal: evento creato '{summary}' — {event.get('id')}")
    return {
        "id": event.get("id", ""),
        "summary": event.get("summary", ""),
        "start": event.get("start", {}).get("dateTime", ""),
        "end": event.get("end", {}).get("dateTime", ""),
        "html_link": event.get("htmlLink", ""),
    }


async def create_all_day_event(
    summary: str,
    date: datetime,
    description: str = "",
) -> dict:
    """Crea un evento giornata intera."""
    token = await _get_access_token()

    date_str = date.strftime("%Y-%m-%d")
    body = {
        "summary": summary,
        "start": {"date": date_str},
        "end": {"date": date_str},
    }
    if description:
        body["description"] = description

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{_GCAL_API}/calendars/{_calendar_id()}/events",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        event = resp.json()

    logger.info(f"GCal: evento all-day creato '{summary}'")
    return {
        "id": event.get("id", ""),
        "summary": event.get("summary", ""),
        "html_link": event.get("htmlLink", ""),
    }


async def update_event(
    event_id: str,
    summary: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    description: str | None = None,
    location: str | None = None,
) -> dict:
    """Aggiorna un evento esistente (solo campi forniti)."""
    token = await _get_access_token()

    body: dict = {}
    if summary is not None:
        body["summary"] = summary
    if start is not None:
        body["start"] = {"dateTime": _to_rfc3339(start), "timeZone": "Europe/Rome"}
    if end is not None:
        body["end"] = {"dateTime": _to_rfc3339(end), "timeZone": "Europe/Rome"}
    if description is not None:
        body["description"] = description
    if location is not None:
        body["location"] = location

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.patch(
            f"{_GCAL_API}/calendars/{_calendar_id()}/events/{event_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        event = resp.json()

    logger.info(f"GCal: evento aggiornato '{event.get('summary')}'")
    return {
        "id": event.get("id", ""),
        "summary": event.get("summary", ""),
        "start": event.get("start", {}).get("dateTime", ""),
        "end": event.get("end", {}).get("dateTime", ""),
    }


async def delete_event(event_id: str) -> bool:
    """Elimina un evento."""
    token = await _get_access_token()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.delete(
            f"{_GCAL_API}/calendars/{_calendar_id()}/events/{event_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        ok = resp.status_code in (200, 204)

    if ok:
        logger.info(f"GCal: evento {event_id} eliminato")
    else:
        logger.error(f"GCal: errore eliminazione {event_id}: {resp.status_code}")
    return ok


async def find_free_slots(
    date: datetime,
    duration_minutes: int = 60,
) -> list[dict]:
    """Trova slot liberi in un giorno. Ritorna lista di {start, end}."""
    events = await get_events_for_date(date)

    day_start = date.replace(hour=8, minute=0, second=0, tzinfo=_TZ)
    day_end = date.replace(hour=20, minute=0, second=0, tzinfo=_TZ)

    busy_slots = []
    for ev in events:
        if ev["all_day"]:
            continue
        try:
            ev_start = datetime.fromisoformat(ev["start"])
            ev_end = datetime.fromisoformat(ev["end"])
            busy_slots.append((ev_start, ev_end))
        except (ValueError, TypeError):
            continue

    busy_slots.sort(key=lambda x: x[0])

    free_slots = []
    cursor = day_start
    duration = timedelta(minutes=duration_minutes)

    for busy_start, busy_end in busy_slots:
        if busy_start > cursor and (busy_start - cursor) >= duration:
            free_slots.append({
                "start": _to_rfc3339(cursor),
                "end": _to_rfc3339(busy_start),
            })
        if busy_end > cursor:
            cursor = busy_end

    if cursor < day_end and (day_end - cursor) >= duration:
        free_slots.append({
            "start": _to_rfc3339(cursor),
            "end": _to_rfc3339(day_end),
        })

    return free_slots
