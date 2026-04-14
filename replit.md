# Pinteresto — Mastermind CEO System

## Overview

Pinteresto is an automated Pinterest marketing system with two layers:

1. **Legacy Agent** — LangGraph agent that fetches Amazon products, generates affiliate links, and posts to Pinterest via Make.com webhooks.
2. **Mastermind CEO System** — A four-node LangGraph pipeline that reads Pinterest analytics, generates strategy via Gemini 1.5, generates SEO copy via Groq/Cerebras, and executes posts — with strict account isolation.

## Tech Stack

- **Language:** Python 3.12
- **Web Framework:** FastAPI + Uvicorn (port 5000)
- **AI — Strategy:** Google Gemini 1.5 Flash (via `google-genai` SDK)
- **AI — Copywriting:** Groq llama-3.3-70b (primary) + Cerebras llama3.3-70b (fallback)
- **AI — Agent Orchestration:** LangGraph + LangChain
- **Database/Storage:** Google Sheets (via gspread)
- **Scheduling:** APScheduler (AsyncIOScheduler, US Eastern Time)
- **Rate Limit Handling:** tenacity (exponential backoff for Gemini 5-6 RPM limit)
- **Image Processing:** Pillow (PIL)
- **Frontend:** Static HTML/JS dashboard served by FastAPI

## Project Structure

```
main.py                      — FastAPI app, APScheduler, all API endpoints
agent.py                     — Legacy LangGraph agent (product fetch → post)
config.py                    — All config & env var constants
requirements.txt

mastermind/
  __init__.py
  state.py                   — MastermindState TypedDict (strict account isolation)
  templates.py               — Local copy fallback templates (per niche, never empty)
  node_data.py               — Node 1: Data Intelligence (analytics fetch, stagnant fallback)
  node_cmo.py                — Node 2: CMO Mastermind (Gemini + tenacity retry)
  node_copy.py               — Node 3: Fast Copywriters (Groq → Cerebras → templates)
  node_execute.py            — Node 4: Execution Engine (image + webhook, never crashes)
  graph.py                   — LangGraph pipeline assembly & run_mastermind() entry point

tools/
  google_drive.py            — Google Sheets: products + get_analytics_rows()
  groq_ai.py                 — AI product filtering & pin copy generation
  llm.py                     — Dual LLM client (Groq + Cerebras fallback)
  aliexpress.py              — Amazon product search via RapidAPI
  admitad.py                 — Amazon affiliate link builder
  make_webhook.py            — Pinterest posting via Make.com webhook (untouched)

utils/
  image_processor.py         — Product image download + Pinterest overlay (untouched)

static/
  index.html                 — Dashboard UI (Legacy controls + Mastermind CEO panel)
```

## Mastermind CEO Pipeline (4 Nodes)

```
[Node 1: Data Intelligence]
  → Fetches last 7 days from Analytics_Log (Acc 1) & Analytics_logs2 (Acc 2)
  → Fallback: injects "Stagnant" profile if gspread fails, never crashes

[Node 2: CMO Mastermind — Gemini 1.5 Flash]
  → Receives isolated metrics per account
  → Decides strategy: "Visual Pivot", "Aggressive Affiliate Strike", or "Viral-Bait"
  → tenacity: 12 s → 24 s → 48 s retries for 5-6 RPM limit
  → Fallback: hardcoded "Visual Pivot" JSON on total Gemini failure

[Node 3: Fast Copywriters — Groq → Cerebras → Local Templates]
  → Generates Pinterest SEO title, description, hashtags per account
  → Groq fails → try Cerebras → fallback to niche-specific local templates
  → Guaranteed non-empty strings. Zero cross-account copy contamination.

[Node 4: Execution Engine]
  → Fetches next PENDING product for correct niche pool
  → Processes image via existing image_processor (untouched)
  → Strips affiliate link if strategy = "Viral-Bait"
  → Fires existing Make.com webhook (untouched)
  → Marks product POSTED in Google Sheets
  → Both accounts run in parallel (asyncio.gather)
  → All calls wrapped in try/except — never crashes the graph
```

## Scheduler (US Eastern Time)

| Time | Job |
|------|-----|
| 9:00 AM | 🧠 Mastermind CEO daily cycle |
| 8:00 AM | Randomizer: schedules 3 random pins per account in 4-10 PM window |
| 5:00 PM | Account 1 fixed pin |
| 6:00 PM | Account 2 fixed pin |
| 8:00 PM | Account 1 fixed pin |
| 9:00 PM | Account 2 fixed pin |
| 4-10 PM | 3 random pins × 2 accounts |

## Required Environment Variables

| Variable | Used By |
|----------|---------|
| `GEMINI_API_KEY` | Mastermind CMO node (Gemini 1.5 Flash) |
| `GROQ_API_KEY` | Copywriters node + legacy agent |
| `CEREBRAS_API_KEY` | Copywriters fallback + legacy agent |
| `GOOGLE_CREDS_JSON` | Google Sheets (service account JSON string) |
| `SPREADSHEET_ID` | Google Sheets spreadsheet ID |
| `RAPIDAPI_KEY` | Amazon product search |
| `MAKE_WEBHOOK_URL` | Account 1 Pinterest webhook |
| `MAKE_WEBHOOK_URL_2` | Account 2 Pinterest webhook |
| `TAVILY_API_KEY` | (Optional) Tavily search |
| `MAX_PRODUCTS_TO_FETCH` | (Optional, default 20) |

## Google Sheets Tabs

| Tab Name | Purpose |
|----------|---------|
| `Approved Deals` | Product inventory (Status: PENDING/POSTED) |
| `Analytics_Log` | Account 1 Pinterest analytics (Date, Impressions, Clicks, Outbound Clicks, Saves) |
| `Analytics_logs2` | Account 2 Pinterest analytics (same columns) |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard UI |
| `/api/stats` | GET | Legacy agent stats |
| `/api/products` | GET | All products from Sheets |
| `/api/mastermind/stats` | GET | Mastermind CEO runtime state |
| `/api/mastermind/run` | POST | Trigger full Mastermind cycle |
| `/api/run-agent` | POST | Legacy: full agent run |
| `/api/run-account1` | POST | Legacy: Account 1 only |
| `/api/run-account2` | POST | Legacy: Account 2 only |
| `/api/fill-niches` | POST | Detect & fill missing niches |
| `/api/fetch-products` | POST | Fetch new products from Amazon |
| `/api/chat` | POST | AI chat assistant |

## Account Isolation

**Account 1 — HomeDecor:**
- Niches: home, kitchen, cozy, gadgets, organize
- Analytics: `Analytics_Log`
- Board IDs: defined in `config.py` PINTEREST_ACCOUNTS[0]

**Account 2 — Tech:**
- Niches: tech, budget, phone, smarthome, wfh
- Analytics: `Analytics_logs2`
- Board IDs: defined in `config.py` PINTEREST_ACCOUNTS[1]

Zero cross-contamination: state keys are prefixed `a1_` / `a2_`, copy prompts specify the niche, and product fetching filters by niche list.

## Deployment

- Target: `vm` (always-running — required for APScheduler in-memory state)
- Command: `gunicorn --bind=0.0.0.0:5000 --reuse-port --worker-class uvicorn.workers.UvicornWorker main:app`
