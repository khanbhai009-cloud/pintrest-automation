# Pinteresto v3 — 100% Visual Strategy System

## Overview

Pinteresto is an automated Pinterest marketing system managing 2 niche accounts (HomeDecor, Tech).
**v3 is a 100% Visual Strategy** — every pin is a VIRAL_PIN with AI-generated imagery.
Product sourcing and affiliate links are fully disabled (code preserved but not called).

## Tech Stack

- **Language:** Python 3.12
- **Web Framework:** FastAPI + Uvicorn (port 5000)
- **AI — CMO Strategy:** Google Gemini 2.5 Flash (primary) → Cerebras qwen-3-235b (fallback)
- **AI — Image Gen:** OpenRouter FLUX → Pollinations.ai (free, URL-based)
- **AI — Agent Execution:** Groq llama-3.3-70b (primary) + Cerebras (fallback)
- **AI — Agent Orchestration:** LangGraph + LangChain
- **Analytics Source:** Google Sheets (via gspread) — read-only for analytics
- **Scheduling:** APScheduler (AsyncIOScheduler, US Eastern Time)
- **Image Hosting:** ImgBB (mandatory gateway before every Pinterest post)
- **Delivery:** Make.com webhooks → Pinterest API

## v3 Visual Styles (CMO picks based on analytics)

| Style Key | Label | Description |
|-----------|-------|-------------|
| `green_minimalist` | Green Minimalist Interior | Lush plants, white walls, natural light, Scandinavian-biophilic |
| `sunset_landscape` | Sunset Landscape | Golden hour, dramatic skies, cinematic open horizons |
| `cozy_architecture` | Cozy Aesthetic Architecture | Wooden beams, stone fireplaces, hygge atmosphere |
| `cinematic_retro` | Cinematic Retro Scenes | 35mm film grain, vintage color grading, nostalgic urban |

## Project Structure

```
main.py                      — FastAPI app, APScheduler, all API endpoints
agent.py                     — LangGraph visual agent (v5 — 100% VIRAL_PIN)
config.py                    — All config, env var constants, AI model names

mastermind/
  __init__.py
  state.py                   — MastermindState TypedDict (strict account isolation)
  templates.py               — Local copy fallback templates (legacy, kept for reference)
  node_data.py               — Node 1: Data Intelligence (analytics fetch, stagnant fallback)
  node_cmo.py                — Node 2: CMO Mastermind (Gemini 2.5 Flash -> Cerebras, always VIRAL_PIN)
  node_copy.py               — Node 3: Fast Copywriters (legacy, not in active graph)
  node_execute.py            — Node 4: Execution Engine (generate_pin_image only, no products)
  graph.py                   — LangGraph pipeline (data -> CMO -> agent_executor -> END)

tools/
  image_creator.py           — OpenRouter FLUX -> Pollinations T2I pipeline + ImgBB upload
  google_drive.py            — Google Sheets: analytics read only (no product writes in v3)
  groq_ai.py                 — AI product filtering (legacy, not called in v3)
  llm.py                     — Dual LLM client (Groq + Cerebras fallback)
  aliexpress.py              — Product search (kept, NOT called in v3)
  admitad.py                 — Affiliate link builder (kept, NOT called in v3)
  make_webhook.py            — Pinterest posting via Make.com webhook
  tavily_search.py           — Web search (optional)

utils/
  image_processor.py         — Image processing utils (legacy)

static/
  index.html                 — Dashboard UI
```

## v3 Mastermind Pipeline (3 Active Nodes)

```
[Node 1: Data Intelligence]
  → Fetches last 30 days from Analytics_Log (Acc 1) & Analytics_logs2 (Acc 2)
  → Fallback: injects "Stagnant" profile if gspread fails

[Node 2: CMO Mastermind — Gemini 2.5 Flash -> Cerebras]
  → Always outputs VIRAL_PIN — no AFFILIATE_PIN routing
  → Analyzes analytics to pick best Visual Style from 4 options
  → Hardcoded fallback: cozy_architecture (Acc1), cinematic_retro (Acc2)

[Node 3: Agent Executor — Groq -> Cerebras]
  → run_agent() called with injected CMO strategy
  → publish_next_pin(visual_style) generates AI image + posts to Pinterest
  → No product sourcing, no affiliate links
```

## Scheduler

- **10 pins/day** — 5 per account (all VIRAL_PIN)
- **Window:** 7:30 AM → 7:30 PM EST
- **Interleaved:** A1, A2, A1, A2... with min 25 min gap

## Required Environment Variables

| Variable | Used By |
|----------|---------|
| `GEMINI_API_KEY` | CMO Mastermind (Gemini 2.5 Flash) |
| `GROQ_API_KEY` | Agent execution LLM |
| `CEREBRAS_API_KEY` | CMO fallback + agent fallback |
| `OPENROUTER_API_KEY` | Image generation (FLUX) |
| `IMGBB_API_KEY` | Image hosting |
| `GOOGLE_CREDS_JSON` | Google Sheets analytics (service account JSON string) |
| `SPREADSHEET_ID` | Google Sheets spreadsheet ID |
| `MAKE_WEBHOOK_URL` | Account 1 Pinterest webhook |
| `MAKE_WEBHOOK_URL_2` | Account 2 Pinterest webhook |

## AI Model Constants (all centralized in config.py)

| Constant | Value |
|----------|-------|
| `GEMINI_CMO_MODEL` | gemini-2.5-flash-preview-04-17 |
| `CEREBRAS_CMO_MODEL` | qwen-3-235b-a22b-instruct-2507 |
| `GROQ_MODEL` | llama-3.3-70b-versatile |
| `OPENROUTER_IMAGE_MODEL` | black-forest-labs/flux-1.1-pro |
| `POLLINATIONS_MODEL` | flux (free fallback) |

## Google Sheets Tabs

| Tab Name | Purpose |
|----------|---------|
| `Analytics_Log` | Account 1 Pinterest analytics |
| `Analytics_logs2` | Account 2 Pinterest analytics |
| `Approved Deals` | (Legacy) Product inventory — not used in v3 |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard UI |
| `/api/stats` | GET | Agent stats |
| `/api/mastermind/stats` | GET | Mastermind runtime state |
| `/api/mastermind/run` | POST | Trigger full Mastermind cycle |
| `/api/run-agent` | POST | Manual agent run |
| `/api/run-account1` | POST | Account 1 only |
| `/api/run-account2` | POST | Account 2 only |
| `/api/chat` | POST | AI chat assistant |

## Deployment

- Target: `vm` (always-running — required for APScheduler)
- Port: 5000
- Command: `python main.py`
