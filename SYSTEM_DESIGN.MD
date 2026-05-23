# Pinteresto v3 — System Design Document

> **Last updated:** Auto-generated from full codebase analysis.
> This document is the single source of truth for architecture, data flow, and operational logic.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture Diagram](#2-architecture-diagram)
3. [File-by-File Breakdown](#3-file-by-file-breakdown)
4. [Complete Pipeline Flow](#4-complete-pipeline-flow)
5. [Data Flow](#5-data-flow)
6. [API & External Services](#6-api--external-services)
7. [Error Handling & Fallbacks](#7-error-handling--fallbacks)
8. [Scheduler Logic](#8-scheduler-logic)
9. [Vision Feeder System](#9-vision-feeder-system)
10. [Known Issues & TODOs](#10-known-issues--todos)

---

## 1. System Overview

Pinteresto v3 is a **fully autonomous Pinterest marketing engine**. Once deployed, it requires zero manual intervention: it self-schedules, self-generates content, self-publishes, and self-adapts based on analytics feedback.

### What it does

- **Generates AI art-directed lifestyle images** using a triple-redundant text-to-image pipeline.
- **Writes viral Pinterest copy** (title, description, tags, alt-text) using a 3-tier LLM stack.
- **Finds and purchases Amazon affiliate products** matching the niche of each pin.
- **Writes and publishes SEO blog posts** to Firebase Firestore linked back to each pin.
- **Posts to Pinterest** via Make.com automation webhooks.
- **Learns from aesthetics** via a Vision Feeder that analyzes Google Drive inspiration images with Gemini Vision.

### Accounts

| Account | Niche | Styles | Pinterest Boards |
|---------|-------|--------|-----------------|
| `account_1` | HomeDecor & Lifestyle | 11 styles | home, kitchen, cozy, gadgets, organize |
| `account_2` | Tech & WFH Aesthetic | 5 styles | tech, budget, phone, smarthome, wfh |

### Scale

- **20 pins/day** (10 per account)
- **60–72 minute gaps** between pins, randomized
- **Interleaved** A1/A2 posting
- **24/7 autonomous** operation via APScheduler

---

## 2. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         REPLIT HOST                                  │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  FastAPI (main.py) — port 5000                                  │ │
│  │                                                                   │ │
│  │   /          dashboard HTML                                      │ │
│  │   /status    scheduler + queue state                            │ │
│  │   /trigger   manual run                                         │ │
│  │   /products  Google Sheets product table                        │ │
│  │   /analytics Pinterest analytics                                │ │
│  │   /vision/*  Vision Feeder controls                             │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│           │ APScheduler (AsyncIOScheduler)                            │
│           │                                                           │
│     ┌─────▼──────────────────────────────────┐                       │
│     │  mastermind_scheduled_job()             │  every 60–72 min     │
│     │    → run_mastermind(account)            │  interleaved A1/A2   │
│     └─────────────────────────────────────────┘                       │
│           │                                                           │
│     ┌─────▼──────────────────────────────────────────────────────┐   │
│     │  LangGraph: MASTERMIND GRAPH  (mastermind/graph.py)        │   │
│     │                                                              │   │
│     │   ┌──────────────────────┐                                  │   │
│     │   │ node_data_intelligence│  Reads analytics from Sheets    │   │
│     │   └──────────┬───────────┘                                  │   │
│     │              │ MastermindState                               │   │
│     │   ┌──────────▼───────────┐                                  │   │
│     │   │  node_cmo_mastermind │  Gemini → Cerebras → hardcoded   │   │
│     │   │  (Style rotation +   │  Builds visual_prompt, copy,     │   │
│     │   │   LLM strategy gen)  │  style_key, ratio, niche         │   │
│     │   └──────────┬───────────┘                                  │   │
│     │              │                                               │   │
│     │   ┌──────────▼───────────┐                                  │   │
│     │   │  node_agent_executor │  Invokes run_agent()             │   │
│     │   └──────────┬───────────┘                                  │   │
│     └──────────────┼─────────────────────────────────────────────┘   │
│                    │                                                   │
│     ┌──────────────▼─────────────────────────────────────────────┐   │
│     │  LangGraph: AGENT  (agent.py)                               │   │
│     │   Tool: fill_missing_niches()   → Sheets product CRUD       │   │
│     │   Tool: publish_next_pin()      → Full pin pipeline         │   │
│     └──────────────┬──────────────────────────────────────────────┘   │
│                    │                                                   │
│     ┌──────────────▼──────────────────────────────────────────────┐   │
│     │  publish_next_pin()  (agent.py)                              │   │
│     │                                                               │   │
│     │  1. get_pending_products()     ← Google Sheets               │   │
│     │  2. generate_pin_image()       ← T2I pipeline                │   │
│     │  3. _upload_to_imgbb()         ← ImgBB hosting               │   │
│     │  4. _run_inline_blog()         ← Blog pipeline               │   │
│     │  5. post_to_pinterest()        ← Make.com webhook            │   │
│     │  6. mark_as_posted()           ← Google Sheets               │   │
│     └─────────────────────────────────────────────────────────────┘   │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │  VISION FEEDER (tools/visions_ai.py) — background asyncio loop │  │
│  │   Google Drive images → Gemini Vision → Prompts_Master (Sheet) │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘

EXTERNAL SERVICES
─────────────────
Google Sheets ←→ Products, Prompts_Master, Style_Tracker, Prompt_Tracker,
                  Vision_Tracker, Analytics_Log, Analytics_logs2
Firebase Firestore ← Blog posts (SEO articles)
ImgBB ← Generated pin images (permanent CDN hosting)
Make.com ← Pinterest posting automation (2 webhooks: A1 + A2)
Gemini 2.5 Flash ← CMO strategy + Vision Feeder
Groq llama-3.3-70b ← LLM fallback + fast copywriting
Cerebras qwen-3-235b ← LLM third-tier
Cloudflare Workers AI ← T2I primary (FLUX.1-schnell)
HuggingFace ← T2I secondary (FLUX.1-schnell)
Pollinations.ai ← T2I last resort
RapidAPI (Amazon) ← Product search primary
Apify ← Product search fallback
Google Drive ← Aesthetic inspiration images (Vision Feeder source)
```

---

## 3. File-by-File Breakdown

### Root Level

#### `main.py`
**Role:** Application entrypoint. FastAPI server + scheduler bootstrap + dashboard API.

**Key responsibilities:**
- Defines `lifespan()` context manager:
  - Calls `init_sheets()` to auto-create missing Google Sheet tabs
  - Starts `AsyncIOScheduler` via `schedule_jobs()`
  - Starts Vision Feeder background task loop
- Registers all FastAPI routes (`/`, `/status`, `/trigger`, `/trigger/{account}`, `/products`, `/analytics`, `/pin-queue`, `/vision/*`)
- Implements `mastermind_scheduled_job(account)` — the core periodic function
- Implements `run_mastermind(account)` — runs the LangGraph mastermind pipeline
- Implements `vision_feeder_loop()` — background asyncio loop for Vision Feeder
- Serves `static/index.html` as the dashboard SPA

**Scheduler setup** (`schedule_jobs()`):
- Starts with a 5-second initial delay, then randomized 60–72 min gaps
- Interleaves account_1 and account_2 calls
- Adds a pin watchdog job every 30 minutes

---

#### `agent.py`
**Role:** LangGraph agent that actually executes pins. Called by `node_agent_executor`.

**Tools registered:**
1. `fill_missing_niches(account_key)` — Finds products in Sheets without a `niche` column value, asks the LLM to assign one, writes back to Sheets
2. `publish_next_pin(account_key, strategy, visual_style, niche, visual_prompt, title, description, tags, alt_text, ratio)` — Full pin publishing pipeline

**`publish_next_pin()` internal flow:**
1. Pull up to 2 pending products from Google Sheets (`get_pending_products`)
2. Generate pin image via `generate_pin_image(visual_prompt, ratio)` → ImgBB URL
3. If image fails → use product's own `image_url` as fallback
4. Run inline blog pipeline: `_run_inline_blog()` → Firebase slug/URL
5. Build Pinterest payload (image_url, title, description, tags, alt_text, blog_url, product affiliate links)
6. Send to Make.com webhook (`post_to_pinterest()`)
7. Mark product as POSTED in Google Sheets (`mark_as_posted()`)
8. Return structured result dict

**`_run_inline_blog()` — Inline Blog Pipeline (V4):**
```
node_blog_trigger → node_product_researcher → node_blog_writer → node_firebase_publisher
```
This runs inside `publish_next_pin()` as a 4-step sequential function call chain (not a separate LangGraph graph). The output is a Firebase blog URL included in the Pinterest pin.

---

#### `config.py`
**Role:** Central config and secret loading.

**Environment variables:**
| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` | Google Gemini 2.5 Flash (CMO + Vision Feeder) |
| `GROQ_API_KEY` | Groq llama-3.3-70b (LLM fallback + aliexpress vision) |
| `CEREBRAS_API_KEY` | Cerebras qwen-3-235b (LLM third-tier) |
| `GOOGLE_CREDS_JSON` | Google Service Account JSON (Sheets + Drive access) |
| `SPREADSHEET_ID` | Google Sheets spreadsheet ID |
| `SHEET_NAME` | Products tab name (default: `Products`) |
| `IMGBB_API_KEY` | ImgBB image hosting |
| `MAKE_WEBHOOK_URL` | Make.com webhook → Pinterest Account 1 |
| `MAKE_WEBHOOK_URL_2` | Make.com webhook → Pinterest Account 2 |
| `FIREBASE_CREDS_JSON` | Firebase service account JSON |
| `RAPIDAPI_KEY` | RapidAPI (Amazon product search) |
| `AMAZON_STORE_ID` | Amazon Associates tag (affiliate links) |
| `APIFY_API_KEY` | Apify scraper (Amazon fallback) |
| `APIFY_ACTOR_ID` | Apify actor for Amazon scraping |
| `GITHUB_TOKEN` | GitHub Models API (vision selection fallback in aliexpress.py) |

---

### `mastermind/` — LangGraph Strategy Engine

#### `mastermind/graph.py`
**Role:** Assembles the 3-node LangGraph `StateGraph`.

**Graph definition:**
```
START → node_data_intelligence → node_cmo_mastermind → node_agent_executor → END
```

**State type:** `MastermindState` (TypedDict defined in `state.py`)

**Entry point:** `run_mastermind(account_key: str)` — compiles and runs the graph synchronously.

---

#### `mastermind/state.py`
**Role:** Defines `MastermindState` TypedDict shared between all graph nodes.

**Fields:**
```python
{
  "account_key": str,           # "account_1" or "account_2"
  "analytics": list,            # Raw analytics rows from Sheets
  "strategy": dict,             # CMO output: pin type, visual style, copy, prompts
  "execution_result": dict,     # Agent tool call result
  "error": str | None,          # Error message if any node fails
}
```

---

#### `mastermind/node_data.py` — Data Intelligence Node
**Role:** Feeds the CMO with real performance data.

**What it does:**
- Calls `get_analytics_rows(sheet_name, days=7)` for the relevant account tab (`Analytics_Log` for A1, `Analytics_logs2` for A2)
- Returns last 7 days of Pinterest analytics: Date, Impressions, Clicks, Outbound Clicks, Saves
- On failure: logs warning and passes empty analytics (stagnant fallback) so pipeline continues

---

#### `mastermind/node_cmo.py` — CMO Mastermind Node
**Role:** The creative brain. Decides what to post, what it should look like, and writes the copy.

**Visual Styles (hardcoded in VISUAL_STYLES dict):**

*Account 1 — HomeDecor (11 styles):*
- `boho_aesthetic_study` — Rattan, gallery wall, pothos, warm wood
- `pastel_dreamy_kitchen` — Pink cabinets, cherry blossom, marble counters
- `sunflower_yellow_porch` — Yellow blooms, wicker swing, citrus tones
- `sage_copper_dining` — Forest green walls, copper cookware, botanical prints
- `golden_balcony_garden` — Citrus trees, terracotta pots, warm afternoon light
- `jungle_biophilic_bedroom` — Oversized tropical leaves, rattan headboard
- `yellow_kawaii_bedroom` — Mustard yellow, plush toys, sunflower bedding
- `warm_minimalist_bedside` — Beige linen, wooden lamp, soft shadows
- `cottagecore_tech_den` — Antique books, dark academia, vintage monitor
- `enchanted_cottage_garden` — Stone pathway, climbing roses, fairy lights

*Account 2 — Tech (5 styles):*
- `kawaii_pastel_gaming` — Pastel pink gaming, LED lighting, plushies
- `sage_clean_workspace` — Sage green wall, MacBook, succulent
- `yellow_creator_flatlay` — Mustard headphones, yellow roses, MacBook overhead
- `warm_minimalist_bedside` — Shared with A1

**Style Rotation Logic:**
1. Loads current style index from `Style_Tracker` sheet tab (TTL-cached 5 min → local JSON fallback)
2. Fetches prompt rows from `Prompts_Master` sheet (TTL-cached 30 min)
3. Picks the next style by index (`style_idx % len(styles_for_account)`)
4. Within each style, rotates through available prompt rows from `Prompts_Master` using `Prompt_Tracker`
5. Saves updated indices back to `Style_Tracker` and `Prompt_Tracker`

**LLM Strategy Generation (3-tier fallback):**
1. **Gemini 2.5 Flash** (primary) — `gemini-2.5-flash-preview-05-20` via `google.generativeai`
2. **Cerebras qwen-3-235b** (secondary) — on Gemini failure/429
3. **Hardcoded `HARDCODED_FALLBACK` dict** (emergency) — when both LLMs fail

**Output fields** (stored in `state["strategy"]`):
```json
{
  "pin_type": "VIRAL_PIN",
  "strategy": "...",
  "visual_style": "boho_aesthetic_study",
  "niche": "cozy",
  "vibe": "...",
  "title": "...",
  "description": "...",
  "tags": ["...", "...", "...", "...", "..."],
  "alt_text": "...",
  "visual_prompt": "..., 4K ultra HD, photorealistic, highly detailed, award-winning photography",
  "ratio": "9:16"
}
```

**Validation:**
- Enforces `pin_type == "VIRAL_PIN"`
- Truncates `alt_text` to 200 chars (Pinterest API limit)
- Appends `4K ultra HD, photorealistic, highly detailed, award-winning photography` if missing from `visual_prompt`

---

#### `mastermind/node_execute.py` — LEGACY (not in active graph)
**Role (historical):** Was an earlier execution node. Replaced by `node_agent_executor` + `agent.py`.
**Status:** Dead code. Not imported in `graph.py`.

---

#### `mastermind/node_copy.py` — LEGACY (not in active graph)
**Role (historical):** "Fast Copywriters" node using Groq→Cerebras→local templates for pin copy.
**Status:** Dead code. Not imported in `graph.py`. The CMO node now handles copy generation.

---

#### `mastermind/node_blog_trigger.py` — Blog Trigger Node
**Role:** Entry point of the inline blog pipeline. Decides whether to run a blog for this pin.

**Logic:**
- Checks if product data and CMO strategy are sufficient to generate a blog
- Prepares the blog generation context (niche, style, product list, CMO copy)
- Passes to `node_product_researcher`

---

#### `mastermind/node_product_researcher.py` — Product Researcher Node
**Role:** Finds Amazon products relevant to the pin's niche/style to embed in the blog.

**Uses:**
- `tools/aliexpress.py` → `search_products()` — hybrid RapidAPI→Apify Amazon search
- `tools/admitad.py` → `enrich_with_affiliate_link()` — appends `?tag=AMAZON_STORE_ID`
- Vision AI (`get_best_lifestyle_image()`) — Groq Vision→GitHub Models to select best product image

**Product quality filter:** rating ≥ 3.5 AND reviews ≥ 50

---

#### `mastermind/node_blog_writer.py` — Blog Writer Node
**Role:** Generates full SEO HTML blog post.

**LLM fallback chain (4 tiers):**
1. Gemini 2.5 Flash
2. Groq llama-3.3-70b
3. Cerebras qwen-3-235b
4. Local template from `mastermind/templates.py`

**Output:** Full HTML blog post with:
- SEO title and meta description
- Pin image embedded
- 3-5 product recommendations with affiliate links
- Structured sections (intro, product reviews, buying guide, conclusion)
- Schema markup ready for Firebase hosting

---

#### `mastermind/node_firebase_publisher.py` — Firebase Publisher Node
**Role:** Publishes the blog post to Firebase Firestore.

**Uses:** `tools/firebase_publisher.py`
**Output:** `{ "slug": "...", "blog_url": "/blog/...", "success": true }`

---

#### `mastermind/templates.py`
**Role:** Local copy fallback templates for all 10 niches (home, kitchen, cozy, gadgets, organize, tech, budget, phone, smarthome, wfh).

Used by `node_copy.py` (legacy) and as the last-resort copy fallback when all LLMs fail.

---

### `tools/` — External Integration Tools

#### `tools/image_creator.py` — T2I Image Pipeline
**Role:** Generates a pin image from a text prompt. Triple-redundant engine.

**3-tier fallback:**
```
1. Cloudflare Workers AI  →  FLUX.1-schnell  (primary, free tier)
2. HuggingFace Inference  →  FLUX.1-schnell  (secondary)
3. Pollinations.ai        →  free public API  (last resort)
```

**Supported ratios:** `9:16` (1080×1920), `1:1` (1080×1080), `4:5` (1080×1350), `16:9` (1920×1080)

**Post-generation:**
- All generated images are uploaded to **ImgBB** for permanent CDN hosting
- Returns permanent ImgBB URL (not the T2I provider's temporary URL)
- On upload failure: falls back to the raw T2I URL

**Key function:** `generate_pin_image(prompt: str, ratio: str = "9:16") -> str | None`

---

#### `tools/make_webhook.py` — Pinterest Poster
**Role:** Sends pin data to Make.com automation, which posts to Pinterest.

**Webhook routing:**
- `account_1` → `MAKE_WEBHOOK_URL`
- `account_2` → `MAKE_WEBHOOK_URL_2`

**Payload:**
```json
{
  "image_url": "https://i.ibb.co/...",
  "title": "...",
  "description": "...",
  "tags": ["...", "..."],
  "alt_text": "...",
  "link": "https://yoursite.com/blog/slug",
  "board": "home"
}
```

**Key function:** `post_to_pinterest(account_key, image_url, title, description, tags, alt_text, link, board) -> dict`

---

#### `tools/visions_ai.py` — Vision Feeder Agent
**Role:** Extracts "aesthetic DNA" from inspiration images and writes prompt rows to `Prompts_Master`.

**Full flow:**
1. Reads images from a Google Drive folder (via Google Drive API)
2. Checks `Vision_Tracker` sheet to skip already-processed files
3. Enforces daily limit of 10 images (configurable)
4. For each new image: sends to **Gemini Vision** (`gemini-2.5-flash-preview-05-20`)
5. Gemini extracts: `style_key`, `label`, `description`, `t2i_base`, `niche_affinity`, `tags`
6. Appends extracted row to `Prompts_Master` Google Sheet
7. Logs to `Vision_Tracker` sheet with status

**Pause/resume:** Controlled via `VISION_FEEDER_PAUSED` flag (toggled by `/vision/pause` and `/vision/resume` endpoints)

**Key function:** `run_vision_feeder(account: str) -> dict`

---

#### `tools/llm.py` — Dual LLM Client
**Role:** Shared LLM utility used by multiple nodes for text generation.

**Priority:**
1. **Groq** `llama-3.3-70b-versatile` (fast, cheap)
2. **Cerebras** `qwen-3-235b` (fallback on Groq failure/429)

**Key function:** `ask_llm(prompt: str, system: str = None) -> str`

---

#### `tools/firebase_publisher.py` — Firebase Firestore Client
**Role:** Publishes blog posts to Firebase Firestore. Used by `node_firebase_publisher`.

**Collection:** `blog_posts` (configurable)
**Document ID:** URL slug derived from blog title
**Fields stored:** `title`, `slug`, `html_content`, `meta_description`, `created_at`, `niche`, `account`, `image_url`, `tags`

**Key function:** `publish_blog(blog_data: dict) -> dict`

---

#### `tools/aliexpress.py` — Amazon Product Search
**Role:** Searches Amazon for products matching a keyword/niche. Despite the filename, this module searches Amazon (not AliExpress) — the name is a historical artifact.

**2-engine hybrid:**
1. **RapidAPI** `realtime-amazon-data.p.rapidapi.com` (primary, real-time)
2. **Apify** Amazon scraper actor (fallback — slower but more reliable)

**Vision image selection (within aliexpress.py):**
- `get_best_lifestyle_image(image_urls)` — uses Groq Vision→GitHub Models to pick the most lifestyle-appropriate product image from a gallery

**Quality filter:** rating ≥ 3.5, reviews ≥ 50

**Key function:** `search_products(keyword, niche, max_results=5) -> list[dict]`

---

#### `tools/admitad.py` — Affiliate Link Generator
**Role:** Appends Amazon Associates tag to product URLs.

**Key function:** `enrich_with_affiliate_link(product: dict) -> dict`
**Config:** `AMAZON_STORE_ID` env var

---

#### `tools/google_drive.py` — Backward Compatibility Layer
**Role:** Re-exports all `sheets/` functions under the old `tools/google_drive` import path. Exists to avoid breaking legacy import statements.

---

### `sheets/` — Google Sheets Data Layer

The entire Google Sheets interaction is encapsulated in this package.

#### `sheets/base.py`
- Singleton `gspread.Client` (authenticated once, reused)
- Service account auth from `GOOGLE_CREDS_JSON`
- `_throttled_write()` enforces 1.2s minimum gap between write calls (rate-limit protection)
- `reset_client()` forces re-auth on next call

#### `sheets/products.py`
CRUD for the **Products** tab:
- `get_pending_products(limit, allowed_niches)` — Filters by `Status == "PENDING"`
- `mark_as_posted(product_name)` — Sets `Status = "POSTED"`
- `save_products(products)` — Batch append rows
- `count_pending()`, `get_all_products()`, `get_products_without_niche()`, `update_niche()`

#### `sheets/prompts_master.py`
- **Prompts_Master** tab: style prompts database
- Columns: `style_key`, `account`, `label`, `description`, `t2i_base`, `niche_affinity`, `tags`
- **30-minute TTL in-memory cache** — new Vision Feeder rows auto-picked up within 30 min
- `append_prompt_row(data)` — used by Vision Feeder to add new aesthetic DNA rows

#### `sheets/style_tracker.py`
- **Style_Tracker** tab: per-account style rotation indices
- Columns: `account_1`, `account_2` (values = current style index integers)
- **5-minute TTL in-memory cache** → local JSON fallback (`data/style_tracker_local.json`)
- Always writes local JSON first, then Sheets (best-effort)

#### `sheets/prompt_tracker.py` *(not read, inferred from __init__.py)*
- **Prompt_Tracker** tab: per-style prompt rotation indices
- Columns: `tracker_key`, `last_idx`
- Tracks which prompt row within each style was last used

#### `sheets/vision_tracker.py` *(not read, inferred from __init__.py)*
- **Vision_Tracker** tab: audit log of Vision Feeder processed images
- Columns: `date`, `file_name`, `style_key`, `account`, `status`, `timestamp`
- `get_today_count_from_sheet()` — enforces daily image limit

#### `sheets/analytics.py`
- Reads **Analytics_Log** (A1) and **Analytics_logs2** (A2) tabs
- Multi-format date parsing: `%Y-%m-%d`, `%m/%d/%Y`, `%d/%m/%Y`, `%d-%m-%Y`, `%B %d, %Y`
- Returns last N days of rows; falls back to last N rows if date parsing fails

#### `sheets/setup.py`
- `init_sheets()` — called at startup; auto-creates any missing tabs with correct headers
- Idempotent: won't touch tabs that already exist and have headers
- Required tabs: `Prompts_Master`, `Style_Tracker`, `Prompt_Tracker`, `Vision_Tracker`, `Analytics_Log`, `Analytics_logs2`

---

### `pipeline/` — Legacy Full Pipeline Orchestrator

#### `pipeline/orchestrator.py`
**Status:** Fully implemented but **not connected to the scheduler**. This is an alternate, more verbose 9-step pipeline for future use or manual invocation.

**Steps:**
```
1. Keyword Agent        → get_todays_keywords()
2. Pin Content Agent    → generate_pin_content()
3. Prompt Selector      → select_best_prompt()
4. Image Creator        → generate_pin_image()
5. Product Extractor    → extract_products_from_image()
6. Amazon Fetcher       → fetch_amazon_products()
7. Blog Agent           → generate_blog_post()
8. Firebase Publisher   → publish_blog_to_firebase()
9. Pinterest Publisher  → publish_pin()
```

This pipeline is currently a separate codebase within the repo and is **not invoked by any scheduler or endpoint** in the active system.

---

### `utils/`

#### `utils/image_processor.py`
**Role:** PIL-based image overlay utility (currently unused in main flow).

**Functionality:** Downloads an image URL, resizes to 1000×1500 (Pinterest optimal), adds a dark gradient overlay at the bottom, renders title text and CTA text. Returns JPEG bytes.

**Status:** Utility function available but not called in the active pin publishing flow. Originally intended for product image overlays.

---

### `static/index.html`
**Role:** Single-page dashboard UI served at `/`.

**Shows:**
- Scheduler status (running/stopped, next job time)
- Recent pin queue (last N pins posted per account)
- Analytics summary
- Vision Feeder status and controls (pause/resume/trigger)
- Manual trigger buttons per account

---

## 4. Complete Pipeline Flow

### Active Production Flow (scheduler-triggered)

```
APScheduler tick (every 60–72 min, alternating A1/A2)
│
├─ mastermind_scheduled_job(account_key)
│   └─ run_mastermind(account_key)
│       └─ LangGraph: MASTERMIND GRAPH
│
│   [NODE 1] node_data_intelligence
│   ├─ get_analytics_rows(sheet_name, days=7)
│   ├─ Returns: state["analytics"] = [{"Date":…, "Impressions":…, …}, …]
│   └─ Failure: state["analytics"] = [] (pipeline continues)
│
│   [NODE 2] node_cmo_mastermind
│   ├─ load_style_tracker()          → current style index (Sheets → local JSON)
│   ├─ get_prompts_master()          → all prompt rows (30-min cache)
│   ├─ pick next style by rotation index
│   ├─ _get_prompt_for_style()       → pick next prompt row for that style
│   ├─ _build_forced_style_prompt()  → build LLM prompt with art direction context
│   ├─ LLM call (3-tier):
│   │   ├─ Gemini 2.5 Flash          (primary)
│   │   ├─ Cerebras qwen-3-235b      (fallback on 429/error)
│   │   └─ HARDCODED_FALLBACK dict   (emergency)
│   ├─ _extract_json()               → parse LLM response
│   ├─ _validate()                   → enforce VIRAL_PIN, alt_text ≤ 200 chars
│   ├─ save_style_tracker()          → advance style index
│   ├─ save_prompt_tracker()         → advance prompt index
│   └─ Returns: state["strategy"] = {pin_type, visual_style, niche, visual_prompt,
│                                     title, description, tags, alt_text, ratio}
│
│   [NODE 3] node_agent_executor
│   └─ run_agent(account_key, strategy)
│       └─ LangGraph: AGENT GRAPH
│           ├─ Tool call: fill_missing_niches(account_key)
│           │   ├─ get_products_without_niche()  → Sheets
│           │   ├─ LLM assigns niche to each
│           │   └─ update_niche()                → Sheets
│           │
│           └─ Tool call: publish_next_pin(…all CMO strategy fields…)
│               │
│               ├─ [STEP 1] get_pending_products(limit=2, allowed_niches=[niche])
│               │   └─ Google Sheets → Products tab, Status==PENDING
│               │
│               ├─ [STEP 2] generate_pin_image(visual_prompt, ratio)
│               │   ├─ Cloudflare Workers AI (FLUX.1-schnell)  → bytes
│               │   ├─ HuggingFace (FLUX.1-schnell)            → bytes (fallback)
│               │   └─ Pollinations.ai                         → bytes (last resort)
│               │       └─ _upload_to_imgbb(bytes) → permanent ImgBB URL
│               │
│               ├─ [STEP 3, optional] product image fallback
│               │   └─ If T2I fails AND product has image_url → use product image
│               │
│               ├─ [STEP 4] _run_inline_blog(account, strategy, product, image_url)
│               │   ├─ node_blog_trigger()
│               │   │   └─ Decide: run blog? Prepare context.
│               │   ├─ node_product_researcher()
│               │   │   ├─ search_products(keyword, niche)
│               │   │   │   ├─ RapidAPI Amazon search   (primary)
│               │   │   │   └─ Apify Amazon scrape      (fallback)
│               │   │   ├─ get_best_lifestyle_image()
│               │   │   │   ├─ Groq Vision              (primary)
│               │   │   │   └─ GitHub Models            (fallback)
│               │   │   └─ enrich_with_affiliate_link() → ?tag=AMAZON_STORE_ID
│               │   ├─ node_blog_writer()
│               │   │   ├─ Gemini 2.5 Flash             (primary)
│               │   │   ├─ Groq llama-3.3-70b           (fallback)
│               │   │   ├─ Cerebras qwen-3-235b         (fallback)
│               │   │   └─ Local template               (last resort)
│               │   └─ node_firebase_publisher()
│               │       └─ Firebase Firestore → blog_posts/{slug}
│               │           └─ Returns: blog_url = "/blog/{slug}"
│               │
│               ├─ [STEP 5] post_to_pinterest(account_key, payload)
│               │   └─ Make.com webhook (MAKE_WEBHOOK_URL or MAKE_WEBHOOK_URL_2)
│               │       └─ Make.com → Pinterest API → Pin posted
│               │
│               └─ [STEP 6] mark_as_posted(product_name)
│                   └─ Google Sheets: Status → "POSTED"
│
└─ Pin published. Next job scheduled in 60–72 min.
```

---

## 5. Data Flow

### Google Sheets — Central Database

```
Spreadsheet ID: env[SPREADSHEET_ID]

Tab: Products
  Columns: product_name | product_id | sale_price | rating | orders |
           affiliate_link | image_url | keyword | niche | Status
  Flow: Amazon search → save_products() → PENDING → publish_next_pin() → POSTED

Tab: Prompts_Master
  Columns: style_key | account | label | description | t2i_base | niche_affinity | tags
  Flow: Vision Feeder → append_prompt_row() | CMO → get_prompts_master() (30-min cache)

Tab: Style_Tracker
  Columns: account_1 | account_2
  Values:  current rotation index per account
  Flow: CMO reads → increments → saves (Sheets + local JSON)

Tab: Prompt_Tracker
  Columns: tracker_key | last_idx
  Flow: CMO reads → increments → saves

Tab: Vision_Tracker
  Columns: date | file_name | style_key | account | status | timestamp
  Flow: Vision Feeder → log_to_vision_tracker() after each image processed

Tab: Analytics_Log       (Account 1 Pinterest analytics)
Tab: Analytics_logs2     (Account 2 Pinterest analytics)
  Columns: Date | Impressions | Clicks | Outbound Clicks | Saves
  Flow: Manual upload from Pinterest → Data Intelligence node reads
```

### Firebase Firestore — Blog Backend

```
Collection: blog_posts
Document:   {slug}
Fields:     title, slug, html_content, meta_description, created_at,
            niche, account, image_url, tags

Flow: node_blog_writer → HTML → node_firebase_publisher → Firestore
      Pinterest pin link_url = "https://yoursite.com/blog/{slug}"
```

### ImgBB — Image CDN

```
Flow: T2I engine → raw bytes → ImgBB API → permanent URL (i.ibb.co/...)
      Pinterest payload image_url = ImgBB permanent URL
```

### In-Memory Caches

| Cache | TTL | Fallback |
|-------|-----|---------|
| `Prompts_Master` rows | 30 min | Raises (caller handles) |
| `Style_Tracker` values | 5 min | Local `data/style_tracker_local.json` |
| gspread client singleton | lifetime | `reset_client()` on auth error |
| Products worksheet | lifetime | Re-opens on next call |

---

## 6. API & External Services

### LLMs

| Service | Model | Use Case | Priority |
|---------|-------|----------|---------|
| Google Gemini | `gemini-2.5-flash-preview-05-20` | CMO strategy, blog writing, Vision Feeder | 1st |
| Groq | `llama-3.3-70b-versatile` | LLM fallback, copywriting, vision selection | 2nd |
| Cerebras | `qwen-3-235b` | 3rd-tier LLM fallback | 3rd |
| GitHub Models | `Llama-3.2-11B-Vision-Instruct` | Product image selection fallback | last |

### Image Generation

| Service | Model | Endpoint | Priority |
|---------|-------|----------|---------|
| Cloudflare Workers AI | FLUX.1-schnell | `https://api.cloudflare.com/client/v4/accounts/{id}/ai/run/@cf/black-forest-labs/flux-1-schnell` | 1st |
| HuggingFace | FLUX.1-schnell | `https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell` | 2nd |
| Pollinations.ai | — | `https://image.pollinations.ai/prompt/{encoded_prompt}` | 3rd |

### Product Data

| Service | Endpoint | Priority |
|---------|----------|---------|
| RapidAPI Amazon | `realtime-amazon-data.p.rapidapi.com` | 1st |
| Apify Amazon Scraper | `api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items` | 2nd |

### Pinterest Posting

| Service | Method | Details |
|---------|--------|---------|
| Make.com | HTTP POST webhook | Separate webhook URLs per account. Make.com handles Pinterest API auth. |

### Storage & Hosting

| Service | Use | Auth |
|---------|-----|------|
| Google Sheets | Products DB, trackers, analytics, prompts | Service account JSON |
| Google Drive | Vision Feeder source images | Same service account |
| Firebase Firestore | Blog post storage | Firebase service account JSON |
| ImgBB | Permanent image CDN | API key |

---

## 7. Error Handling & Fallbacks

### LLM Fallback Chain (CMO Node)

```
Gemini 2.5 Flash
  ↓ (error or 429)
Cerebras qwen-3-235b
  ↓ (error)
_build_from_style_data() — builds valid strategy dict from VISUAL_STYLES hardcoded data
  ↓ (style not even in VISUAL_STYLES)
HARDCODED_FALLBACK[account_key] — guaranteed working pin per account
```

### Image Generation Fallback Chain

```
Cloudflare Workers AI (FLUX.1-schnell)
  ↓ (fail/timeout)
HuggingFace (FLUX.1-schnell)
  ↓ (fail/timeout)
Pollinations.ai (free, no auth)
  ↓ (all fail)
None — agent falls back to product's own image_url from Sheets
```

### ImgBB Upload Fallback

```
Upload to ImgBB
  ↓ (fail)
Return raw T2I provider URL (temporary, may expire)
```

### Google Sheets Fallbacks

```
Style_Tracker:
  Sheets read → in-memory TTL cache → local data/style_tracker_local.json → {}

Prompts_Master:
  Sheets read (cached 30 min) → Raises on failure
  CMO handles: falls back to VISUAL_STYLES hardcoded descriptions

Products:
  If 0 pending products → runs VIRAL_PIN mode (aesthetic-only pin, no product)
```

### Blog Pipeline Fallbacks

```
Blog Writer LLMs:
  Gemini → Groq → Cerebras → local template (mastermind/templates.py)

Firebase Publish:
  On failure → pin is still posted with a fallback blog_url slug
  Pipeline does NOT abort on Firebase failure
```

### Amazon Product Search Fallbacks

```
RapidAPI
  ↓ (fail or returns non-list)
Apify
  ↓ (fail or 400)
[] — no products; blog continues without product recommendations
```

### Analytics Node Fallback

```
Sheets read
  ↓ (fail)
state["analytics"] = [] — CMO still runs; uses "no data" context in prompt
```

### Rate Limiting

- **Sheets writes:** 1.2-second minimum gap enforced by `_throttled_write()` in `sheets/base.py`
- **Amazon API:** 2s delay between detail calls, 5s spacing between vision calls (in `aliexpress.py`)
- **Gemini 429:** Triggers immediate fallback to Cerebras (no retry loop — avoids blocking the scheduler)

---

## 8. Scheduler Logic

### Setup (`main.py → schedule_jobs()`)

```python
AsyncIOScheduler()  # APScheduler, shares FastAPI's asyncio event loop

Initial delay: 5 seconds after startup
Then: randomized 60–72 minute gaps between jobs

Account interleaving: A1, A2, A1, A2, ... (alternates every tick)

Watchdog: every 30 minutes → checks if last pin was posted; reschedules if stalled
```

### Job Sequence (per tick)

```
1. mastermind_scheduled_job(account_key) called
2. Logs: "🎯 Mastermind job START: account_1"
3. run_mastermind(account_key) → LangGraph pipeline (see Section 4)
4. Logs result (success/failure, pin title, style used)
5. Schedules NEXT tick: now + random(60, 72) minutes for the OTHER account
```

### Pin Watchdog (every 30 min)

- Checks `last_posted_time` global variable
- If time since last successful post exceeds threshold → logs alert
- Designed to detect scheduler stalls (e.g., if a long-running LLM call blocks the event loop)

### Manual Trigger

- `POST /trigger` → `run_mastermind("account_1")`
- `POST /trigger/{account}` → `run_mastermind(account)` where account is `account_1` or `account_2`
- Runs immediately in the background (FastAPI BackgroundTask)

---

## 9. Vision Feeder System

**Purpose:** Continuously learn new aesthetic styles from inspiration images uploaded to Google Drive. Automatically expands the `Prompts_Master` sheet with new T2I prompts.

### Flow

```
Google Drive folder
  │  (images uploaded manually by user)
  ▼
vision_feeder_loop()  (background asyncio task, main.py)
  │  Runs continuously with 1-hour sleep between iterations
  │
  ▼
run_vision_feeder(account)  (tools/visions_ai.py)
  │
  ├─ 1. List files in Google Drive folder
  ├─ 2. get_all_processed_filenames()  → Vision_Tracker sheet (skip already done)
  ├─ 3. get_today_count_from_sheet()   → enforce daily limit (default: 10 images)
  │
  └─ For each new image (up to daily limit):
      ├─ Download image bytes from Drive
      ├─ Send to Gemini Vision with art-direction extraction prompt
      ├─ Parse response: {style_key, label, description, t2i_base, niche_affinity, tags}
      ├─ append_prompt_row(data)  → write to Prompts_Master (invalidates 30-min cache)
      └─ log_to_vision_tracker()  → write to Vision_Tracker
```

### Controls (via API)

| Endpoint | Action |
|----------|--------|
| `POST /vision/pause` | Sets `VISION_FEEDER_PAUSED = True` |
| `POST /vision/resume` | Sets `VISION_FEEDER_PAUSED = False` |
| `POST /vision/trigger` | Force-runs one Vision Feeder cycle immediately |
| `GET /vision/status` | Returns paused state, today's count, recent processed files |

---

## 10. Known Issues & TODOs

### Active Issues

| # | Severity | Description |
|---|----------|-------------|
| 1 | High | `tools/aliexpress.py` searches **Amazon** (not AliExpress). Filename is a misleading historical artifact. |
| 2 | Medium | `pipeline/orchestrator.py` and its sub-agents (`pipeline/keyword_agent.py`, etc.) are implemented but **not connected** to any scheduler or endpoint in `main.py`. They are effectively dead code parallel to the active mastermind flow. |
| 3 | Medium | `mastermind/node_execute.py` and `mastermind/node_copy.py` are **not imported** in `graph.py` — dead code from an older architecture version. |
| 4 | Medium | `utils/image_processor.py` (PIL overlay) is implemented but **not called** anywhere in the active flow. |
| 5 | Low | `data/style_tracker_local.json` and `data/prompt_tracker.json` — the `data/` directory must exist before first write; if it doesn't, `os.makedirs` handles it, but this is not guaranteed to work in all deployment environments. |
| 6 | Low | Rate limiting on Gemini (429) is handled by immediately falling back to Cerebras — there is no exponential backoff or retry queue. Under heavy load, Gemini quota exhaustion permanently shifts all traffic to Cerebras until the next restart. |
| 7 | Low | The Vision Feeder's daily limit is stored per-calendar-day in `Vision_Tracker` sheet. If the scheduler timezone differs from the user's local timezone, the "today" boundary may not align with expectations. |

### TODOs / Future Improvements

| # | Priority | Description |
|---|----------|-------------|
| 1 | High | **Connect `pipeline/orchestrator.py`** to the scheduler or provide a dashboard endpoint to run it — it offers a more granular, keyword-driven pipeline. |
| 2 | High | **Add real Pinterest analytics auto-import** — currently `Analytics_Log` must be manually updated by copying from Pinterest analytics. Automating this via Pinterest API or Zapier would close the feedback loop fully. |
| 3 | Medium | **Remove dead code:** `node_execute.py`, `node_copy.py`, `utils/image_processor.py`, rename `tools/aliexpress.py` → `tools/amazon.py`. |
| 4 | Medium | **Persistent job state:** APScheduler uses an in-memory job store. On restart, the next-tick schedule resets. Migrate to SQLAlchemy job store for persistence across restarts. |
| 5 | Medium | **Pinterest board routing:** Currently the Make.com webhook receives a `board` field (niche name), but the actual board routing logic lives inside Make.com. Moving board selection into `tools/make_webhook.py` would make it testable and auditable. |
| 6 | Medium | **Blog frontend:** Firebase Firestore stores blog HTML but there is no frontend to serve it. A static Next.js/Astro site reading from Firestore would complete the SEO funnel. |
| 7 | Low | **Webhook failure alerting:** If Make.com returns a non-200, it is logged but not alerted. Adding a Slack/email alert on Pinterest post failure would improve operational visibility. |
| 8 | Low | **Product inventory auto-refill:** When `count_pending()` drops below a threshold, the system should trigger `search_products()` automatically and backfill the Products sheet. Currently this requires manual product sourcing. |
| 9 | Low | **Vision Feeder style deduplication:** If Gemini Vision extracts a `style_key` that already exists in `Prompts_Master`, it adds a duplicate row. A dedup check before `append_prompt_row()` would keep the sheet clean. |

---

*End of System Design Document*
