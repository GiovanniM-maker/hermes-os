# AI Daily Intelligence + Content Factory (n8n)

Editorial assistant pipeline that ingests AI/business-AI news daily, ranks it for an
Italian audience (entrepreneurs / SMEs / solo pros), drafts Instagram + LinkedIn
content packages via OpenRouter, and delivers them to Telegram.

Everything is **not** an autopublisher — it's an editorial aide. No content is
pushed to social platforms automatically.

## Deployed workflows

| File                             | Name                              | n8n ID             |
|----------------------------------|-----------------------------------|--------------------|
| workflows/00_setup_sheet.json    | AI_Daily_Setup_Sheet              | VmLCoG6ZFytfdJbN   |
| workflows/01_intelligence.json   | AI_Daily_Intelligence             | qq6reINIwJ7m7ga9   |
| workflows/02_content_factory.json| AI_Daily_Content_Factory          | hdOf3dbF1YBum4hl   |
| workflows/03_delivery.json       | AI_Daily_Delivery_And_Logging     | nT88zYs1r1IOmqV8   |

## Credentials used

| Credential type  | n8n ID              | Purpose            | Source        |
|------------------|---------------------|--------------------|---------------|
| googleApi        | VjDfIwHmyAdswLjT    | Google Sheets API  | pre-existing  |
| openRouterApi    | mpMk74pCZg2Efk6i    | LLM (OpenRouter)   | pre-existing  |
| telegramApi      | LB71gUXSNc4EH9v1    | Content Bot        | created here  |

Telegram bot: `@juan_ai_content_bot` (id 8633658100).

## Spreadsheet

- Target: `1yIzIep-XdRV7EVeWhjdpUps1PlF7tN6KymRjRgXGtuk`
- Tabs the setup workflow will create (if missing):
  - `source_registry`, `fallback_library`, `run_logs`,
    `ranked_items_history`, `content_history`, `publication_feedback`
- Tabs are seeded for `source_registry` (14 curated sources) and
  `fallback_library` (7 evergreen topics).

## Required manual steps before first run

1. **Share the target spreadsheet with the Google service account** used by
   credential `googleApi` (`VjDfIwHmyAdswLjT`). Open n8n → Credentials →
   _Google Sheets account_ → copy the `email` → share the sheet (Editor).
2. **Send `/start` to `@juan_ai_content_bot`** so a chat exists, then retrieve
   the `chat_id` from `https://api.telegram.org/bot<TOKEN>/getUpdates`.
3. Put the `chat_id` into the `Config` node of
   `AI_Daily_Delivery_And_Logging` (field `telegramChatId`).
4. Open `AI_Daily_Setup_Sheet` in the n8n UI and click **Execute Workflow**
   (or POST the webhook; see below). It creates tabs and headers and seeds
   `source_registry` + `fallback_library`.
5. Activate `AI_Daily_Intelligence`. It runs Mon–Fri 08:00 Europe/Rome.

### Triggering the setup workflow

```
curl -X POST https://giovannimavilla.app.n8n.cloud/webhook/ai-daily-setup-init \
     -H "Content-Type: application/json" -d '{}'
```

## Architecture

```
Schedule 08:00 M-F (WF1 Intelligence)
  → read source_registry (Sheets API)
  → Route by type (rss | html)
     → RSS Feed Read / HTTP fetch + HTML anchor extraction
  → Merge → Dedupe (canonical URL + normalized title) + date window
  → OpenRouter scoring (JSON output: candidate/publishable/confidence/topic)
  → Mode selection (FULL_NEWS | HYBRID | FALLBACK | MONITOR_ONLY | HARD_STOP)
  → Append ranked_items_history
  → Execute WF2 (Content Factory) with envelope
     → per job: OpenRouter package generation (claim + angle + IG + LI + QC)
     → assemble content package, apply leak/confidence safety rules
     → Append content_history
     → Return packages
  → Execute WF3 (Delivery)
     → Build digest + per-package Telegram messages (HTML parse mode,
       split at 3800 chars, retry once)
     → Append run_logs
```

## Run modes

| Mode         | Trigger                                   | Output                                 |
|--------------|-------------------------------------------|----------------------------------------|
| FULL_NEWS    | ≥3 publishable items                      | digest + 3 packages + 2 backup items   |
| HYBRID       | 1–2 publishable items                     | 1-2 news packages + fallback filler    |
| FALLBACK     | 0 publishable, fallback library available | 3 evergreen/trend/practical packages   |
| MONITOR_ONLY | Weak day (some signals only)              | digest + signals, no packages          |
| HARD_STOP    | No items at all / severe failures         | digest with alert, no packages         |

Thresholds (configurable in WF1 `Config` node):
- `candidate_score >= 7.0`
- `publishable_score >= 8.0`
- `confidence >= 0.75`

## Editorial rules enforced by WF2

- Italian, first person, simple, non-hype, non-corporate, non-guru.
- If source is a leak and the LLM didn't label it as such → force `status=review`.
- If `confidence_label=low` + `status=ready` → force downgrade to `review`.
- If LLM returns invalid JSON → package produced with `status=discarded` and
  `qc_reason=invalid_llm_json_or_no_response`.

## Sheet schema

### source_registry
`source_id | name | url | type | tier | enabled | topic_scope | trust_score | notes`

### fallback_library
`fallback_id | category | title | angle | target | priority | enabled`

### run_logs
`run_id | run_date | mode | sources_total | sources_failed | raw_items_count | deduped_count | selected_count | telegram_status | notes | started_at | ended_at`

### ranked_items_history
`run_id | item_id | title | url | source_name | published_at | primary_topic | candidate_score | publishable_score | confidence | selected_yes_no | selection_reason`

### content_history
`content_id | run_id | item_id | mode | platform_pair | status | confidence_label | instagram_hook | instagram_script | instagram_caption | instagram_cta | linkedin_post | source_name | source_url | prompt_version`

### publication_feedback
`content_id | published_yes_no | published_date | platform | views | likes | comments | saves | notes`

## Models (default, swap in each workflow's `Config` node)

- `modelMain` = `anthropic/claude-sonnet-4.5`
- `modelQC`   = `openai/gpt-4o-mini`

Both are configured as workflow-level variables — no hard-coded model strings
in prompt nodes, so swapping takes one edit per workflow.

## Testing / debugging

1. **Intelligence only**: open WF1 in n8n editor, click _Execute Workflow_.
   It reads sources, scores, writes to `ranked_items_history`, and stops
   before calling WF2 unless you keep `Call Content Factory` active.
2. **End-to-end manual run**: execute WF1 → observe all three workflows.
3. **Check error output**: n8n Executions panel → filter by workflow.

## Known limitations / follow-ups

- Source-level `source_name`/`source_tier` is lost in the normalize step
  because `rssFeedRead` fans out per item without carrying the source
  context. Enhancement: prepend an "Enrich with Source" Code node that uses
  `$pairedItem()` to attach source metadata.
- HTML extraction is intentionally light (anchor-based). For sources like
  `anthropic.com/news` consider a dedicated CSS selector node or switch to
  the RSS endpoint if available.
- The `Call Content Factory` / `Call Delivery` nodes pass the envelope via
  `workflowInputs` — the receiving workflows read from the first input item.
- `TELEGRAM_CHAT_ID` is a placeholder until the user messages the bot.
