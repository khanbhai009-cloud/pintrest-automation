<div align="center">

# 📌 PINTERESTO — Finisher Tech AI
### Autonomous Pinterest Marketing System powered by Multi-Agent AI

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.135-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.1-FF6B35?style=for-the-badge)](https://langchain-ai.github.io/langgraph)
[![Gemini](https://img.shields.io/badge/Gemini-2.5_Flash-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://deepmind.google/gemini)
[![Groq](https://img.shields.io/badge/Groq-Llama_3.3_70B-F55036?style=for-the-badge)](https://groq.com)

> **6 Pinterest pins per day. 2 accounts. Zero human input.**  
> A fully autonomous AI system that reads real analytics, decides strategy, generates images, and posts to Pinterest — all on its own.

</div>

---

## ✨ What This Does

Pinteresto is a production-grade Pinterest automation engine. It runs a complete marketing pipeline every day:

```
📊 Reads Analytics  →  🧠 AI Decides Strategy  →  🎨 Generates Images  →  📌 Posts to Pinterest
```

- **Account 1 — HomeDecor** → niches: `home`, `kitchen`, `cozy`, `gadgets`, `organize`
- **Account 2 — Tech** → niches: `tech`, `budget`, `phone`, `smarthome`, `wfh`
- **Schedule** → 3 random slots/account/day (Account 1: 10AM–4PM EST | Account 2: 7PM–1AM EST)

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PINTERESTO PIPELINE v3                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   APScheduler (main.py)                                                     │
│        │  Triggers 3 random slots/day per account                           │
│        ▼                                                                     │
│   ┌─────────────────────────────────────────────┐                           │
│   │       MASTERMIND GRAPH (mastermind/)         │                           │
│   │                                             │                           │
│   │  [Node 1] node_data_intelligence            │                           │
│   │      └─ Reads 7-day analytics from          │                           │
│   │         Google Sheets (both accounts)       │                           │
│   │                  │                          │                           │
│   │                  ▼                          │                           │
│   │  [Node 2] node_cmo_mastermind (Gemini)      │                           │
│   │      └─ 70/30 routing decision              │                           │
│   │         VIRAL_PIN (70%) or                  │                           │
│   │         AFFILIATE_PIN (30%)                 │                           │
│   │         Generates: title, desc, tags,       │                           │
│   │         visual_prompt                       │                           │
│   │                  │                          │                           │
│   │                  ▼                          │                           │
│   │  [Node 3] node_agent_executor               │                           │
│   │      └─ Calls agent.py with CMO strategy    │                           │
│   └─────────────────────────────────────────────┘                           │
│        │                                                                     │
│        ▼                                                                     │
│   ┌──────────────────────────────────────────────┐                          │
│   │        LANGGRAPH AGENT (agent.py)             │                          │
│   │                                              │                          │
│   │  Step 1: fill_missing_niches()               │                          │
│   │  Step 2: analyze_niche_stock()               │                          │
│   │  Step 3: fetch_aliexpress_products() [opt]   │                          │
│   │  Step 4: publish_next_pin()                  │                          │
│   │                   │                          │                          │
│   │          ┌────────┴────────┐                 │                          │
│   │          │  70/30 routing  │                 │                          │
│   │          ▼                 ▼                 │                          │
│   │    VIRAL_PIN          AFFILIATE_PIN          │                          │
│   │    T2I image          Raw product image      │                          │
│   │    No affiliate       Affiliate link kept    │                          │
│   └──────────────────────────────────────────────┘                          │
│        │                                                                     │
│        ▼                                                                     │
│   ImgBB Upload  →  Make.com Webhook  →  📌 Pinterest Pin Live!             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🧠 The 70/30 Content Strategy

The CMO brain (Gemini) independently routes each account every cycle using weighted randomness:

```
┌──────────────────────────────────┬──────────────────────────────────────┐
│        VIRAL_PIN (70%)           │        AFFILIATE_PIN (30%)           │
├──────────────────────────────────┼──────────────────────────────────────┤
│ Goal: Grow reach & algorithm     │ Goal: Drive sales & revenue          │
│ trust                            │                                      │
│                                  │                                      │
│ Image: AI-generated aesthetic    │ Image: Raw product photo             │
│        via Pollinations/Puter    │        (no AI generation)            │
│                                  │                                      │
│ Affiliate Link: STRIPPED         │ Affiliate Link: KEPT                 │
│                                  │                                      │
│ Copy: Aesthetic, inspirational   │ Copy: Benefit-driven + CTA           │
│       no sales pitch             │       "Shop via link in bio"         │
└──────────────────────────────────┴──────────────────────────────────────┘
```

---

## 🤖 AI Stack

| Layer | Model | Role |
|-------|-------|------|
| **CMO Strategist** | Google Gemini 2.5 Flash | Reads analytics, makes 70/30 routing decision, writes full pin content (title, desc, tags, visual_prompt) |
| **Execution Agent** | Groq Llama 3.3 70B | LangGraph tool-calling agent — decides which tools to invoke and in what order |
| **Fallback LLM** | Cerebras Llama 3.3 70B | Automatic failover when Groq is unavailable |
| **Product Filter** | Groq Llama 3.3 70B | Screens Amazon products for quality & Pinterest fit |
| **Image Gen (Primary)** | Pollinations.ai (Flux) | Free T2I — 1024×1792 Pinterest portrait |
| **Image Gen (Fallback)** | Puter.js free tier | T2I backup using Puter credentials |

---

## 🗂️ Project Structure

```
pinteresto/
│
├── main.py                   ← FastAPI server + APScheduler (entry point)
├── agent.py                  ← LangGraph tool-calling execution agent
├── config.py                 ← All environment variable definitions
├── requirements.txt          ← Python dependencies
│
├── mastermind/               ← CEO Pipeline (Mastermind Graph)
│   ├── graph.py              ← 3-node LangGraph pipeline orchestrator
│   ├── state.py              ← Shared TypedDict state (zero cross-contamination)
│   ├── node_data.py          ← Node 1: Reads Google Sheets analytics
│   ├── node_cmo.py           ← Node 2: Gemini CMO — 70/30 routing + content
│   └── node_copy.py          ← (Legacy node — bypassed in v3)
│
├── tools/                    ← Atomic functional units
│   ├── llm.py                ← Unified Groq → Cerebras fallback wrapper
│   ├── aliexpress.py         ← Amazon product search via RapidAPI
│   ├── admitad.py            ← Amazon affiliate link builder
│   ├── google_drive.py       ← Google Sheets CRUD (product DB + analytics)
│   ├── groq_ai.py            ← Product filter + fallback copy generator
│   ├── image_creator.py      ← T2I pipeline (Pollinations → Puter) + ImgBB upload
│   └── make_webhook.py       ← Pinterest poster via Make.com webhook
│
├── static/
│   └── index.html            ← Web dashboard (real-time stats + AI chat)
│
├── README.md                 ← This file
└── SYSTEM_DESIGN.md          ← Deep-dive architecture documentation
```

---

## 🔁 Complete Pin Lifecycle

```
  STOCKING PHASE (when stock is low)
  ────────────────────────────────────────────────────────────────
  Amazon RapidAPI Search
       │  20 raw products returned
       ▼
  Groq LLM Filter
       │  Checks: rating, visual appeal, Pinterest fit, viral potential
       ▼
  Affiliate Link Append
       │  amazon.com/dp/ASIN?tag=swiftmart0008-20
       ▼
  Google Sheets Save
       │  Status = "PENDING"
       ▼
  Ready for publishing ✅


  PUBLISHING PHASE (3x/day per account via scheduler)
  ────────────────────────────────────────────────────────────────
  APScheduler fires at random time slot
       │
       ▼
  node_data_intelligence reads 7-day analytics
       │  impressions_avg, clicks_avg, saves_avg, profile computed
       ▼
  node_cmo_mastermind (Gemini) — 70/30 decision per account
       │
       ├─── 70% → VIRAL_PIN
       │         title, aesthetic description, tags, visual_prompt
       │
       └─── 30% → AFFILIATE_PIN
                 title, CTA description, tags, visual_prompt = "NONE"
       │
       ▼
  node_agent_executor passes strategy → agent.py
       │
       ▼
  fill_missing_niches() → analyze_niche_stock() → [fetch if needed]
       │
       ▼
  publish_next_pin(niche)
       │
       ├─── VIRAL_PIN path:
       │      Pollinations.ai T2I → (fail) → Puter T2I
       │      ImgBB upload (30-min temp URL)
       │      Make.com webhook (NO affiliate link)
       │
       └─── AFFILIATE_PIN path:
              Download raw product image_url
              ImgBB upload (30-min temp URL)
              Make.com webhook (WITH affiliate link)
       │
       ▼
  mark_as_posted() → Google Sheets Status = "POSTED"
       │
       ▼
  📌 Pinterest Pin Live!
```

---

## 🌐 Dashboard & API

A real-time web dashboard is served at the root URL. The following REST endpoints are available:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Web dashboard (HTML) |
| `GET` | `/api/stats` | Product inventory + posting stats |
| `GET` | `/api/mastermind/stats` | CMO pipeline status + scheduled slots |
| `GET` | `/api/products` | First 50 products from Google Sheet |
| `POST` | `/api/mastermind/run` | Manually trigger both accounts |
| `POST` | `/api/mastermind/run-account1` | Manually trigger Account 1 only |
| `POST` | `/api/mastermind/run-account2` | Manually trigger Account 2 only |
| `POST` | `/api/mastermind/stop` | Gracefully stop current cycle |
| `POST` | `/api/fetch-products` | Fetch new products from Amazon |
| `POST` | `/api/fill-niches` | Classify untagged products |
| `POST` | `/api/chat` | AI chat interface (Hinglish) |

---

## ⚙️ Environment Variables

Set these as Replit Secrets (or in `.env` for local development):

```
# ── LLM APIs ──────────────────────────────────────────────
GROQ_API_KEY          Groq API key (primary LLM — Llama 3.3 70B)
CEREBRAS_API_KEY      Cerebras API key (fallback LLM)
GEMINI_API_KEY        Google Gemini API key (CMO Mastermind brain)

# ── Product Sourcing ───────────────────────────────────────
RAPIDAPI_KEY          RapidAPI key for Amazon product search

# ── Google Sheets (Database) ───────────────────────────────
GOOGLE_CREDS_JSON     Service account JSON (stringified, full contents)
SPREADSHEET_ID        Google Spreadsheet ID (from URL)

# ── Image Pipeline ─────────────────────────────────────────
IMGBB_API_KEY         ImgBB API key (mandatory upload gateway)
PUTER_USERNAME        Puter.js account username (T2I fallback)
PUTER_PASSWORD        Puter.js account password (T2I fallback)

# ── Pinterest via Make.com ─────────────────────────────────
MAKE_WEBHOOK_URL      Make.com webhook URL for Account 1 (HomeDecor)
MAKE_WEBHOOK_URL_2    Make.com webhook URL for Account 2 (Tech)
```

---

## 📊 Google Sheets Structure

The system uses **3 sheets** inside one Google Spreadsheet:

### Sheet 1 — `Approved Deals` (Product Database)
| Column | Description |
|--------|-------------|
| `product_name` | Full product title |
| `sale_price` | Product price |
| `rating` | Star rating |
| `affiliate_link` | Amazon link with affiliate tag |
| `image_url` | Product image URL |
| `niche` | Classified niche (e.g. `kitchen`) |
| `Status` | `PENDING` → `POSTED` |

### Sheet 2 — `Analytics_Log` (Account 1 — HomeDecor)
| Column | Description |
|--------|-------------|
| `Date` | Analytics date |
| `Impressions` | Total impressions |
| `Clicks` | Profile clicks |
| `Outbound Clicks` | Link clicks |
| `Saves` | Pin saves |

### Sheet 3 — `Analytics_logs2` (Account 2 — Tech)
Same structure as Sheet 2.

---

## 🛡️ Reliability & Fallback Design

```
Every critical path has a fallback:

LLM:     Groq (primary)  ──fail──▶  Cerebras (fallback)

T2I:     Pollinations    ──fail──▶  Puter free tier
                                         │
                                    ──fail──▶  Raw product image

Gemini:  Live API call   ──fail──▶  Hardcoded "Visual Pivot" strategy
         (with tenacity  (12s → 24s → 48s retry backoff)
```

---

## 🚀 Running Locally

```bash
# 1. Clone the repo
git clone <your-repo-url>
cd pinteresto

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set environment variables in .env file

# 4. Run
python main.py
# Server starts at http://0.0.0.0:5000
```

---

## 🏷️ Tech Stack Summary

| Category | Technology |
|----------|-----------|
| Web Framework | FastAPI + Uvicorn |
| AI Orchestration | LangGraph (StateGraph) |
| Primary LLM | Groq — Llama 3.3 70B |
| Fallback LLM | Cerebras — Llama 3.3 70B |
| CMO Brain | Google Gemini 2.5 Flash Lite |
| Image Generation | Pollinations.ai (Flux model) |
| Image Fallback | Puter.js free tier |
| Image Hosting | ImgBB (30-min temp URLs) |
| Database | Google Sheets via gspread |
| Scheduler | APScheduler (AsyncIO) |
| Pinterest Bridge | Make.com Webhooks |
| Product Source | Amazon via RapidAPI |
| Retry Logic | Tenacity (exponential backoff) |
| HTTP Client | httpx (fully async) |

---

<div align="center">

**Pinteresto v3 — Finisher Tech AI**  
*Built for autonomous scale. Designed to never stop.*

</div>
