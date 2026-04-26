#!/usr/bin/env python3
"""
Eataly image classifier — local batch tool.

Classifica le immagini di una cartella Google Drive con Gemini 2.5 Flash-Lite,
scrive i risultati su Google Sheets, e sposta ogni file nella cartella Drive
della categoria assegnata.

Uso:
    python classify.py --dry-run 20      # processa solo 20 file (test)
    python classify.py                   # full run
    python classify.py --resume          # riprende dove era stato interrotto

Idempotenza: a inizio run legge il foglio output e salta gli ID già scritti.
Se uccidi il processo a metà, basta rilanciarlo: riprende dove era arrivato.
"""

import os
import sys
import io
import json
import time
import base64
import asyncio
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import aiohttp
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from tqdm.asyncio import tqdm as atqdm

# ────────────────────────── CONFIG ──────────────────────────

load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    sys.exit("ERROR: GEMINI_API_KEY non impostata. Mettila in .env o exportala.")

GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

SOURCE_FOLDER  = "1vUrxw22LWZkkeDwGNO1P4sc8FK3Z3v2g"
SPREADSHEET_ID = "1yIzIep-XdRV7EVeWhjdpUps1PlF7tN6KymRjRgXGtuk"
SHEET_TAB      = "image_classification"

FOLDERS = {
    "FRONT":        "15-oP9cJmzs5SQh0hyAhp1hTdi8ZDZBqR",
    "NUDO_PACK":    "1pF6VshXDBte386yzsyzdW4fYoDfDsYzH",
    "TOP":          "125a6QB5UJl22bozKWEQlyNDQaeDeL6K7",
    "TREQUARTI":    "1qIxk1bzfzLy-lB5XUUk_WSfOISPsvLoy",
    "SET":          "1CSIyBUbQe-aSzDUiJpnyh0KoZ17y0V0s",
    "HUMAN_REVIEW": "10WbxpW9feowuLZ9nTilLtlFjWnUNdso1",
    "FAILED":       "1cbAjxtdP1PmnAvprX9SdgMf5DvCd_wa2",
}
VALID_CATS = {"FRONT", "NUDO_PACK", "TOP", "TREQUARTI", "SET"}

CONCURRENCY     = 20    # max chiamate Gemini/Drive in parallelo
APPEND_FLUSH    = 100   # ogni N risultati → batch append su Sheets
RETRY_ATTEMPTS  = 3
RETRY_BASE_WAIT = 2.0

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

PROMPT = """Sei un classificatore esperto di immagini e-commerce alimentari di Eataly. Classifica ogni immagine in UNA SOLA delle 5 categorie qui sotto.

1) FRONT
  - Prodotto confezionato visto FRONTALMENTE (logo centrato, lati assenti o trascurabili).
  - Vale anche se ci sono piccoli "props" alimentari accanto (fettina di pane vicino al vasetto di marmellata, qualche maccherone vicino al pacco di pasta).
  - Vale SEMPRE per BUNDLE e CESTI (set di piu prodotti come unico SKU), a prescindere dall'angolo di scatto.

2) NUDO_PACK
  - Confezione + prodotto "sfuso" della STESSA SKU, visibili nella stessa immagine.
  - Esempi: uovo di Pasqua + scatola, parmigiano confezionato + cuneo di formaggio, panettone + scatola.
  - La confezione DEVE essere visibile insieme al prodotto sfuso.

3) TOP
  - Prodotto confezionato visto DALL'ALTO (asse di scatto perpendicolare al piano).
  - Solo se l'angolo e chiaramente verticale; un'angolazione lieve = TREQUARTI o FRONT.

4) TREQUARTI
  - Prodotto confezionato a 3/4: si vede chiaramente uno spigolo laterale (>=15% del lato).
  - Se il lato e appena accennato (<15%) -> FRONT, non TREQUARTI.
  - Bundle/cesti -> restano FRONT anche se scattati a tre quarti.

5) SET
  - Prodotto NON confezionato, presentato su tagliere, piatto, coppa o ciotola.
  - Nessuna confezione visibile.
  - Vale anche per composite di piu prodotti diversi serviti insieme (es. cuneo di formaggio + crackers su tagliere).

REGOLE
- Una sola categoria. Non inventare etichette.
- In dubbio FRONT vs TREQUARTI -> FRONT.
- In dubbio NUDO_PACK vs SET -> confezione visibile? NUDO_PACK; nessuna confezione? SET.
- Bundle/cesti = sempre FRONT.

CONFIDENCE (0-100)
- 90-100: estremamente sicuro
- 70-89: sicuro
- 50-69: incerto
- <50: molto incerto

NEEDS_HUMAN_REVIEW
- true se confidence < 70
- false se confidence >= 70

OUTPUT: SOLO JSON valido, nessun testo extra."""

GEMINI_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "output":             {"type": "string", "enum": list(VALID_CATS)},
        "confidence":         {"type": "integer", "minimum": 0, "maximum": 100},
        "needs_human_review": {"type": "boolean"},
    },
    "required": ["output", "confidence", "needs_human_review"],
}

# ────────────────────────── LOGGING ──────────────────────────

def setup_logging():
    Path("logs").mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = f"logs/run_{ts}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(logfile),
            logging.StreamHandler(sys.stderr),
        ],
    )
    logging.info(f"Log file: {logfile}")
    return logfile

# ────────────────────────── AUTH ──────────────────────────

def get_credentials():
    """OAuth user flow. First run apre il browser, salva token.json per le run successive."""
    creds = None
    token_path = Path("token.json")
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            secrets_path = Path("client_secrets.json")
            if not secrets_path.exists():
                sys.exit(
                    "ERROR: client_secrets.json mancante. Crealo da:\n"
                    "  GCP Console -> APIs & Services -> Credentials -> Create Credentials\n"
                    "  -> OAuth client ID -> Application type: Desktop app\n"
                    "  -> Download JSON -> rinominalo client_secrets.json e mettilo qui."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())
    return creds

# ────────────────────────── DRIVE / SHEETS HELPERS ──────────────────────────

def list_folder(drive, folder_id):
    """Pagina su Drive API e restituisce la lista completa di file immagine nella cartella."""
    files = []
    token = None
    while True:
        resp = drive.files().list(
            q=f"'{folder_id}' in parents and trashed=false and mimeType contains 'image/'",
            fields="nextPageToken, files(id,name,mimeType,size)",
            pageSize=1000,
            pageToken=token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files.extend(resp.get("files", []))
        token = resp.get("nextPageToken")
        if not token:
            break
    return files

def read_processed_ids(sheets):
    """Legge la colonna ID del foglio output. Restituisce un set."""
    try:
        resp = sheets.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_TAB}!A:A"
        ).execute()
    except Exception as e:
        logging.warning(f"Impossibile leggere il foglio (probabilmente vuoto/nuovo): {e}")
        return set()
    rows = resp.get("values", [])
    ids = set()
    for r in rows[1:]:  # salta header
        if r and r[0]:
            ids.add(r[0])
    return ids

def ensure_sheet_tab(sheets):
    """Crea il tab se non esiste, altrimenti niente."""
    try:
        meta = sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        existing = {s["properties"]["title"] for s in meta.get("sheets", [])}
        if SHEET_TAB in existing:
            return
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": SHEET_TAB}}}]},
        ).execute()
        # write header
        sheets.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_TAB}!A1",
            valueInputOption="USER_ENTERED",
            body={"values": [["ID", "Nome immagine", "Classificazione", "Confidence", "Cluster", "run_id", "parsing_error"]]},
        ).execute()
        logging.info(f"Creato tab '{SHEET_TAB}' con header")
    except Exception as e:
        logging.error(f"Errore ensure_sheet_tab: {e}")

def append_rows(sheets, rows):
    """Append batch di righe al foglio. Una sola call API per tutto il batch."""
    if not rows:
        return
    values = [
        [r["id"], r["name"], r["category"], r["confidence"], r["cluster"], r["run_id"], r.get("parsing_error","")]
        for r in rows
    ]
    sheets.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_TAB}!A:G",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": values},
    ).execute()

# ────────────────────────── PARSING ──────────────────────────

def safe_parse_gemini(text: str) -> Optional[dict]:
    if not text:
        return None
    s = text.strip()
    # strip code fences
    if s.startswith("```"):
        import re
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.I)
        if m:
            s = m.group(1).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    # fallback: outermost {}
    a, b = s.find("{"), s.rfind("}")
    if 0 <= a < b:
        try:
            return json.loads(s[a:b+1])
        except Exception:
            return None
    return None

def decide_dest(category: str, confidence: int, parsing_error: Optional[str]) -> tuple[str, str]:
    """Restituisce (dest_folder_id, cluster_label)."""
    if parsing_error or category not in VALID_CATS:
        return FOLDERS["FAILED"], "failed"
    if confidence < 70:
        return FOLDERS["HUMAN_REVIEW"], "review"
    return FOLDERS[category], "auto"

# ────────────────────────── ASYNC WORKER ──────────────────────────

async def download_drive_file(drive, file_id: str) -> bytes:
    """Sync wrapper in thread, perché googleapiclient non è async."""
    loop = asyncio.get_running_loop()
    def _dl():
        req = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()
    return await loop.run_in_executor(None, _dl)

async def move_drive_file(drive, file_id: str, dest_folder: str, source_folder: str):
    loop = asyncio.get_running_loop()
    def _mv():
        drive.files().update(
            fileId=file_id,
            addParents=dest_folder,
            removeParents=source_folder,
            fields="id,parents",
            supportsAllDrives=True,
        ).execute()
    return await loop.run_in_executor(None, _mv)

async def call_gemini(session: aiohttp.ClientSession, mime_type: str, image_b64: str) -> dict:
    body = {
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": mime_type, "data": image_b64}},
                {"text": PROMPT},
            ]
        }],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 256,
            "responseMimeType": "application/json",
            "responseJsonSchema": GEMINI_RESPONSE_SCHEMA,
        },
    }
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    last_exc = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            async with session.post(GEMINI_URL, json=body, headers=headers, timeout=60) as resp:
                if resp.status == 429 or resp.status >= 500:
                    text = await resp.text()
                    raise RuntimeError(f"Gemini {resp.status}: {text[:200]}")
                resp.raise_for_status()
                return await resp.json()
        except Exception as e:
            last_exc = e
            wait = RETRY_BASE_WAIT * (2 ** attempt)
            logging.warning(f"Gemini retry {attempt+1}/{RETRY_ATTEMPTS} dopo {wait:.1f}s: {e}")
            await asyncio.sleep(wait)
    raise last_exc

async def classify_one(file: dict, drive, session, sem, run_id: str) -> dict:
    async with sem:
        f_id = file["id"]
        name = file["name"]
        mime = file.get("mimeType", "image/jpeg")
        try:
            blob = await download_drive_file(drive, f_id)
            b64 = base64.b64encode(blob).decode()
            resp = await call_gemini(session, mime, b64)
            text = ""
            choices = resp.get("candidates") or []
            if choices and choices[0].get("content", {}).get("parts"):
                text = " ".join(p.get("text", "") for p in choices[0]["content"]["parts"]).strip()
            parsed = safe_parse_gemini(text)
            parsing_error = None
            if parsed and isinstance(parsed, dict):
                category = str(parsed.get("output", "")).strip().upper().replace(" ", "_")
                confidence = max(0, min(100, int(parsed.get("confidence", 0) or 0)))
                if category not in VALID_CATS:
                    parsing_error = f"invalid_category:{category}"
                    category = "ERRORE_VALIDAZIONE"
                    confidence = 0
            else:
                parsing_error = "json_malformato"
                category = "NON_DETERMINATO"
                confidence = 0
            dest, cluster = decide_dest(category, confidence, parsing_error)
            await move_drive_file(drive, f_id, dest, SOURCE_FOLDER)
            return {
                "id": f_id, "name": name, "category": category, "confidence": confidence,
                "cluster": cluster, "run_id": run_id, "parsing_error": parsing_error or "",
                "dest": dest,
            }
        except Exception as e:
            logging.error(f"FAIL {f_id} {name}: {e}")
            return {
                "id": f_id, "name": name, "category": "ERRORE_DOWNLOAD",
                "confidence": 0, "cluster": "failed", "run_id": run_id,
                "parsing_error": str(e)[:200], "dest": FOLDERS["FAILED"],
            }

# ────────────────────────── ORCHESTRATION ──────────────────────────

async def main_async(args):
    logfile = setup_logging()
    creds = get_credentials()
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)

    logging.info("Verifico/creo il tab di output…")
    ensure_sheet_tab(sheets)

    logging.info(f"Listo cartella sorgente {SOURCE_FOLDER}…")
    files = list_folder(drive, SOURCE_FOLDER)
    logging.info(f"Trovati {len(files)} file immagine")

    logging.info("Leggo gli ID già processati nel foglio…")
    processed = read_processed_ids(sheets)
    logging.info(f"Già processati: {len(processed)}")

    todo = [f for f in files if f["id"] not in processed]
    if args.dry_run:
        todo = todo[: args.dry_run]
    logging.info(f"Da processare in questo run: {len(todo)}")
    if not todo:
        logging.info("Niente da fare. Fine.")
        return

    run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    logging.info(f"run_id={run_id} concurrency={CONCURRENCY}")

    sem = asyncio.Semaphore(CONCURRENCY)
    timeout = aiohttp.ClientTimeout(total=120)
    connector = aiohttp.TCPConnector(limit=CONCURRENCY * 2)

    buffer = []
    counts = {"FRONT": 0, "NUDO_PACK": 0, "TOP": 0, "TREQUARTI": 0, "SET": 0,
              "review": 0, "failed": 0}
    failure_log = []

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        tasks = [classify_one(f, drive, session, sem, run_id) for f in todo]
        for coro in atqdm.as_completed(tasks, total=len(tasks), desc="Classifying"):
            try:
                row = await coro
            except Exception as e:
                logging.error(f"Task error: {e}")
                continue
            if row["cluster"] == "failed":
                counts["failed"] += 1
                failure_log.append({"id": row["id"], "name": row["name"], "error": row.get("parsing_error", "")})
            elif row["cluster"] == "review":
                counts["review"] += 1
            else:
                counts[row["category"]] = counts.get(row["category"], 0) + 1
            buffer.append(row)
            if len(buffer) >= APPEND_FLUSH:
                try:
                    append_rows(sheets, buffer)
                    logging.info(f"Flushed {len(buffer)} rows. Counts: {counts}")
                    buffer.clear()
                except Exception as e:
                    logging.error(f"Append fail (verrà ritentato al prossimo flush): {e}")

    if buffer:
        try:
            append_rows(sheets, buffer)
            logging.info(f"Final flush {len(buffer)} rows.")
        except Exception as e:
            logging.error(f"Final append fail: {e}")
            Path("logs/_pending_rows.json").write_text(json.dumps(buffer, ensure_ascii=False, indent=2))

    if failure_log:
        Path(f"logs/failures_{run_id}.json").write_text(json.dumps(failure_log, ensure_ascii=False, indent=2))

    logging.info("=" * 50)
    logging.info(f"DONE — {len(todo)} file processati")
    logging.info(f"Distribuzione: {counts}")
    logging.info(f"Log file: {logfile}")

# ────────────────────────── ENTRY POINT ──────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Eataly image classifier — local batch")
    parser.add_argument("--dry-run", type=int, default=0,
                        help="Processa solo N file (per test). 0 = tutto.")
    args = parser.parse_args()
    asyncio.run(main_async(args))

if __name__ == "__main__":
    main()
