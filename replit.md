# Pinteresto — Pinterest Marketing Bot

## Overview

Pinteresto is an automated Pinterest marketing bot that discovers trending Amazon products via RapidAPI, enriches them with affiliate links, and posts them to Pinterest boards across multiple accounts. It includes a web dashboard for monitoring and manual control.

## Tech Stack

- **Language:** Python 3.12
- **Web Framework:** FastAPI + Uvicorn
- **AI/Agents:** LangGraph + LangChain + Groq (primary) + Cerebras (fallback)
- **Database/Storage:** Google Sheets (via gspread)
- **Scheduling:** APScheduler (AsyncIOScheduler, US Eastern Time)
- **Image Processing:** Pillow (PIL)
- **Frontend:** Static HTML/JS dashboard (Tailwind-styled) served by FastAPI

## Project Structure

```
main.py          — FastAPI app entry point, scheduler setup, API endpoints
agent.py         — LangGraph agent/state machine (Fill Niches → Analyze → Fetch → Post)
config.py        — Centralized config, reads from env vars
tools/
  google_drive.py — Google Sheets integration (product DB)
  groq_ai.py      — AI product filtering and pin copy generation
  llm.py          — Dual LLM client (Groq + Cerebras fallback)
  aliexpress.py   — Amazon product search via RapidAPI
  admitad.py      — Affiliate link enrichment
  make_webhook.py — Pinterest posting via Make.com/Zapier webhook
utils/
  image_processor.py — Product image download and formatting
static/
  index.html      — Dashboard UI
```

## Running the App

The app runs on port 5000:
```
python main.py
```

## Required Environment Variables

| Variable | Description |
|----------|-------------|
| `GROQ_API_KEY` | Groq LLM API key (primary AI provider) |
| `CEREBRAS_API_KEY` | Cerebras API key (fallback AI provider) |
| `GOOGLE_CREDS_JSON` | Google Service Account credentials JSON string |
| `SPREADSHEET_ID` | Google Sheets spreadsheet ID |
| `RAPIDAPI_KEY` | RapidAPI key for Amazon product search |
| `MAKE_WEBHOOK_URL` | Make.com webhook URL for Account 1 (HomeDecor) |
| `MAKE_WEBHOOK_URL_2` | Make.com webhook URL for Account 2 (Tech) |
| `TAVILY_API_KEY` | (Optional) Tavily search API key |
| `MAX_PRODUCTS_TO_FETCH` | (Optional, default 20) Max products per fetch |

## Pinterest Accounts

- **Account 1 - HomeDecor:** home, kitchen, cozy, gadgets, organize niches
- **Account 2 - Tech:** tech, budget, phone, smarthome, wfh niches

## Scheduler

Fixed posts at 5 PM, 6 PM, 8 PM, 9 PM EST daily. Also generates 3 random pins per account in the 4–10 PM EST window each day.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard UI |
| `/api/stats` | GET | Bot stats (pending/posted/running) |
| `/api/products` | GET | All products from Google Sheets |
| `/api/run-agent` | POST | Trigger full automation (both accounts) |
| `/api/run-account1` | POST | Trigger Account 1 only |
| `/api/run-account2` | POST | Trigger Account 2 only |
| `/api/fill-niches` | POST | Detect and fill missing niches |
| `/api/fetch-products` | POST | Fetch new products from Amazon |
| `/api/chat` | POST | AI chat assistant |

## Deployment Notes

- Uses `vm` deployment target (always-running, needed for APScheduler)
- Production command: `gunicorn --bind=0.0.0.0:5000 --reuse-port --worker-class uvicorn.workers.UvicornWorker main:app`
- The app gracefully handles missing API keys — the dashboard still loads but agent operations will fail until keys are configured
