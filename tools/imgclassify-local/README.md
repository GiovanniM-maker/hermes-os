# Eataly image classifier — esecuzione locale

Tool standalone in Python che classifica le immagini Eataly da una cartella
Google Drive con Gemini 2.5 Flash-Lite, scrive i risultati su un Google Sheet,
e sposta i file nelle cartelle Drive corrispondenti alla categoria.

Vive **solo sul tuo computer**. Nessun deployment, nessuna repo, nessuna
credenziale che esce dalla tua macchina.

## Setup (una sola volta, ~10 minuti)

### 1. Crea la cartella e copia i file

```bash
mkdir -p ~/Documents/eataly-classifier
cd ~/Documents/eataly-classifier
# copia qui dentro: classify.py, requirements.txt, .env.example, .gitignore, README.md
```

### 2. Crea l'OAuth client desktop su Google Cloud Console

Per accedere a Drive e Sheets dalla tua macchina, ti serve un client OAuth di
tipo "Desktop app". Si fa una volta e dura sempre.

1. Vai su [console.cloud.google.com](https://console.cloud.google.com/) e seleziona il progetto del cliente.
2. Menu **APIs & Services → Credentials**.
3. Click **Create Credentials → OAuth client ID**.
4. Application type: **Desktop app** → name: "Eataly Classifier" → Create.
5. Click **Download JSON** → rinomina in `client_secrets.json` → mettilo
   nella cartella `~/Documents/eataly-classifier/`.
6. Verifica che siano abilitate le API:
   - **APIs & Services → Library** → cerca "Google Drive API" → Enable.
   - Stessa cosa con "Google Sheets API".

### 3. Imposta la chiave Gemini

```bash
cp .env.example .env
# apri .env e incolla la GEMINI_API_KEY (quella nuova generata su AI Studio)
```

### 4. Crea l'ambiente virtuale Python e installa le dipendenze

```bash
python3 -m venv venv
source venv/bin/activate     # su mac/linux
# su windows powershell: venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 5. Primo avvio (autenticazione browser)

```bash
python classify.py --dry-run 5
```

Al primo run si apre il browser → scegli il tuo account Google → autorizza.
Dopo, si crea `token.json` nella cartella e non te lo richiede più.

## Uso quotidiano

```bash
# 5 file di test rapido
python classify.py --dry-run 5

# 20 file (validazione delle categorie)
python classify.py --dry-run 20

# 100 file (test medio)
python classify.py --dry-run 100

# tutto (~16k)
python classify.py
```

A ogni esecuzione legge il foglio output. **I file già presenti nel foglio
vengono saltati**, quindi puoi rilanciare quanto vuoi senza duplicare:
- crash a metà → rilanci → riprende da dove era
- vuoi solo classificare i nuovi arrivati nella folder → rilanci → fa solo quelli

## Output

- **Sheet** `image_classification` nel tuo Google Sheet (id `1yIzIep…`):
  colonne `ID, Nome immagine, Classificazione, Confidence, Cluster, run_id, parsing_error`
- **Cartelle Drive** popolate:
  - `FRONT` / `NUDO_PACK` / `TOP` / `TREQUARTI` / `SET` per i risultati
    con confidence ≥ 70
  - `Human Review` per confidence < 70 (li rivedi a mano)
  - `Failed` per errori (download fallito, JSON malformato, categoria invalida)
- **Log locale** in `logs/run_YYYYMMDD_HHMMSS.log` + `logs/failures_*.json`
  per ogni run

## Performance

Stima: ~5-7s per immagine, parallelismo 20 → ~70-90 minuti per 16k file.
Configurabile con `CONCURRENCY` in cima al file `classify.py`. Se il
progetto Gemini va in rate-limit, abbassa a 10.

## Costi

Con Gemini 2.5 Flash-Lite ($0.10/1M input, $0.40/1M output) e immagini
~5MB medie + prompt da ~600 token, stima d'ordine di grandezza: **15-30€**
per i 16k file. Misura su un dry run da 100 e moltiplica.

## Sicurezza

- Tutte le credenziali vivono solo nei file:
  - `.env` (Gemini key)
  - `client_secrets.json` (OAuth client)
  - `token.json` (token utente, generato dal flow OAuth)
- Tutti e 3 sono nel `.gitignore` per default.
- **Non condividere mai questi file**. Se sospetti compromissione:
  - `.env` → rigenera la key su AI Studio, sostituiscila
  - `client_secrets.json` → revoca su GCP Console e ricreane uno
  - `token.json` → cancellalo (basta rifare il flow al prossimo run)

## Troubleshooting

**`GEMINI_API_KEY non impostata`** → manca `.env` o la variabile dentro.

**`client_secrets.json mancante`** → segui step 2 del setup.

**Browser non si apre / "redirect_uri_mismatch"** → assicurati che il client
OAuth sia di tipo **Desktop app** (non "Web application").

**`HttpError 403: insufficientPermissions`** → la cartella Drive sorgente
non è accessibile dal tuo account Google. Verifica di poter aprire
manualmente il link `https://drive.google.com/drive/folders/<folder_id>`.

**Crash a metà** → rilancia. L'idempotenza salta gli ID già scritti nel
foglio. I file che il crash ha lasciato non scritti finiscono come failure
solo se erano nel buffer non flushato — controlla `logs/_pending_rows.json`.

**Rate limit Gemini (429)** → il client retry-a automaticamente con backoff
esponenziale. Se persiste, abbassa `CONCURRENCY` a 10 o 5.

## Modificare le categorie / il prompt

Sono in cima a `classify.py`:

- `FOLDERS` — mappa categoria → folder ID Drive
- `VALID_CATS` — set delle categorie ammesse nell'enum Gemini
- `PROMPT` — istruzioni di classificazione
- `GEMINI_RESPONSE_SCHEMA` — schema JSON forzato dell'output

Modifica, salva, rilancia. Niente deploy.
