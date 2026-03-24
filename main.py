import logging
import json
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Tumhare saare custom imports
from agent import run_agent, fill_missing_niches, fetch_aliexpress_products, publish_next_pin
from tools.google_drive import get_all_products, save_products, count_pending
from tools.llm import chat
from config import PINTEREST_ACCOUNTS

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ── Global State ────────────────────────────────────────────
state = {
    "running":      False,
    "last_run":     None,
    "posted_today": 0,
    "last_summary": "Not run yet",
    "last_action":  "—",
}
scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


# ── Scheduler ───────────────────────────────────────────────
async def scheduled_job(trigger: str):
    if state["running"]:
        return
    state["running"]  = True
    state["last_run"] = datetime.now().strftime("%H:%M")
    try:
        result = await run_agent(trigger=trigger)
        state["last_summary"] = result.get("summary", "")
        state["posted_today"] += 1
    except Exception as e:
        state["last_summary"] = f"Error: {e}"
    finally:
        state["running"] = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(scheduled_job, "cron", hour=9,  minute=0, id="morning", kwargs={"trigger": "9AM-IST"})
    scheduler.add_job(scheduled_job, "cron", hour=18, minute=0, id="evening", kwargs={"trigger": "6PM-IST"})
    scheduler.start()
    logger.info("✅ Scheduler active — 9AM + 6PM IST")
    yield
    scheduler.shutdown()


# ── App ─────────────────────────────────────────────────────
app = FastAPI(title="Pinteresto Bot", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Helper ──────────────────────────────────────────────────
def _is_busy():
    return {"status": "busy", "message": "Agent already running — please wait"}


# ── Pages & Health Check ────────────────────────────────────
@app.get("/")
async def dashboard():
    return FileResponse("static/index.html")

# 🔥 Yahi wo missing endpoint hai jiski wajah se 404 aa raha tha!
@app.get("/api/ping")
async def ping():
    return {"status": "ok", "message": "pong"}


# ── Stats & Data ────────────────────────────────────────────
@app.get("/api/stats")
async def get_stats():
    try:
        all_p   = get_all_products()
        pending = sum(1 for p in all_p if p.get("Status") == "PENDING")
        posted  = sum(1 for p in all_p if p.get("Status") == "POSTED")
        total   = len(all_p)

        # Per-niche counts
        niche_counts = {}
        for p in all_p:
            n = p.get("niche", "unknown")
            niche_counts[n] = niche_counts.get(n, 0) + 1
    except:
        pending = posted = total = 0
        niche_counts = {}

    return {
        "pending":      pending,
        "posted":       posted,
        "total":        total,
        "posted_today": state["posted_today"],
        "last_run":     state["last_run"] or "Never",
        "last_summary": state["last_summary"],
        "last_action":  state["last_action"],
        "running":      state["running"],
        "niche_counts": niche_counts,
        "accounts":     [{"name": a["name"], "niche": a["niche"]} for a in PINTEREST_ACCOUNTS],
    }

@app.get("/api/products")
async def get_products():
    try:
        return {"products": get_all_products()}
    except Exception as e:
        return {"products": [], "error": str(e)}

@app.get("/api/agent-status")
async def agent_status():
    return {
        "running":     state["running"],
        "last_run":    state["last_run"] or "Never",
        "last_summary": state["last_summary"],
        "last_action": state["last_action"],
    }


# ── Buttons Action Endpoints ────────────────────────────────
@app.post("/api/run-agent")
async def trigger_agent(background_tasks: BackgroundTasks):
    if state["running"]:
        return _is_busy()

    async def _run():
        state["running"]     = True
        state["last_run"]    = datetime.now().strftime("%H:%M")
        state["last_action"] = "Full Agent Run"
        try:
            result = await run_agent(trigger="manual-api")
            state["last_summary"] = result.get("summary", "")
            state["posted_today"] += 1
        except Exception as e:
            state["last_summary"] = f"Error: {e}"
        finally:
            state["running"] = False

    background_tasks.add_task(_run)
    return {"status": "started", "message": "Full agent running in background"}

@app.post("/api/run-account1")
async def trigger_account1(background_tasks: BackgroundTasks):
    if state["running"]:
        return _is_busy()

    async def _run():
        state["running"]     = True
        state["last_run"]    = datetime.now().strftime("%H:%M")
        state["last_action"] = "Account 1 Pin"
        try:
            result = await run_agent(trigger="manual-account1")
            state["last_summary"] = result.get("summary", "")
            state["posted_today"] += 1
        except Exception as e:
            state["last_summary"] = f"Error: {e}"
        finally:
            state["running"] = False

    background_tasks.add_task(_run)
    return {"status": "started", "message": "Account 1 agent started"}

@app.post("/api/run-account2")
async def trigger_account2(background_tasks: BackgroundTasks):
    if state["running"]:
        return _is_busy()

    async def _run():
        state["running"]     = True
        state["last_run"]    = datetime.now().strftime("%H:%M")
        state["last_action"] = "Account 2 Pin"
        try:
            result = await run_agent(trigger="manual-account2")
            state["last_summary"] = result.get("summary", "")
            state["posted_today"] += 1
        except Exception as e:
            state["last_summary"] = f"Error: {e}"
        finally:
            state["running"] = False

    background_tasks.add_task(_run)
    return {"status": "started", "message": "Account 2 agent started"}

@app.post("/api/fill-niches")
async def trigger_fill_niches(background_tasks: BackgroundTasks):
    if state["running"]:
        return _is_busy()

    async def _run():
        state["running"]     = True
        state["last_action"] = "Fill Niches"
        try:
            result = fill_missing_niches.func()
            state["last_summary"] = result.get("message", "Done")
        except Exception as e:
            state["last_summary"] = f"Fill niches error: {e}"
        finally:
            state["running"] = False

    background_tasks.add_task(_run)
    return {"status": "started", "message": "Filling missing niches..."}

@app.post("/api/fetch-products")
async def trigger_fetch(background_tasks: BackgroundTasks):
    if state["running"]:
        return _is_busy()

    async def _run():
        state["running"]     = True
        state["last_action"] = "Fetch Products"
        try:
            result = await fetch_aliexpress_products.func()
            state["last_summary"] = f"Fetched: {result.get('approved',0)}/{result.get('fetched',0)} approved"
        except Exception as e:
            state["last_summary"] = f"Fetch error: {e}"
        finally:
            state["running"] = False

    background_tasks.add_task(_run)
    return {"status": "started", "message": "Fetching products from AliExpress..."}

@app.post("/api/publish-pin")
async def trigger_publish(background_tasks: BackgroundTasks):
    if state["running"]:
        return _is_busy()

    async def _run():
        state["running"]     = True
        state["last_action"] = "Publish Pin"
        try:
            result = await publish_next_pin.func()
            if result.get("success"):
                state["last_summary"] = f"✅ Posted: {result.get('product','?')} [{result.get('niche','?')}]"
                state["posted_today"] += 1
            else:
                state["last_summary"] = f"❌ Failed: {result.get('reason','?')}"
        except Exception as e:
            state["last_summary"] = f"Publish error: {e}"
        finally:
            state["running"] = False

    background_tasks.add_task(_run)
    return {"status": "started", "message": "Publishing next pin..."}


# ── AI Chat ──────────────────────────────────────────────────
class ChatMessage(BaseModel):
    message: str
    history: list = []

CHAT_SYSTEM = """You are Pinteresto AI — an elite assistant for a Pinterest affiliate marketing automation bot.

You help the owner manage their multi-account Pinterest automation business.

You can:
1. Answer questions about bot performance and stats
2. Generate viral Pinterest content (title, description, hashtags) for any product
3. Suggest Pinterest marketing and growth strategies
4. Help debug issues and optimize the bot

Personality: Direct, professional, friendly. Hinglish ok.
Keep responses concise and actionable."""

@app.post("/api/chat")
async def ai_chat(msg: ChatMessage):
    try:
        try:
            products = get_all_products()
            pending  = sum(1 for p in products if p.get("Status") == "PENDING")
            posted   = sum(1 for p in products if p.get("Status") == "POSTED")
            recent   = [p.get("product_name", "") for p in products[-3:]] if products else []
        except:
            pending = posted = 0
            recent  = []

        context = f"""
Live bot status:
- Running: {state['running']}
- Last run: {state['last_run'] or 'Never'}
- Last action: {state['last_action']}
- Last summary: {state['last_summary']}
- Pending products: {pending}
- Posted products: {posted}
- Posted today: {state['posted_today']}
- Recent products: {', '.join(recent) if recent else 'None'}
"""
        history_text = ""
        for h in msg.history[-6:]:
            role = "User" if h.get("role") == "user" else "Assistant"
            history_text += f"{role}: {h.get('content','')}\n"

        full_prompt = f"{context}\n\nConversation:\n{history_text}User: {msg.message}"
        response    = chat(full_prompt, system=CHAT_SYSTEM, temperature=0.8)
        return {"response": response, "status": "ok"}

    except Exception as e:
        logger.error(f"Chat error: {e}")
        return {"response": "Kuch error aa gaya, dobara try karo!", "status": "error"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
