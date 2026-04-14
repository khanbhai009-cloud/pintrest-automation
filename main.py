import logging
import random
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from agent import run_agent, fill_missing_niches, fetch_aliexpress_products, publish_next_pin
from mastermind.graph import run_mastermind
from tools.google_drive import get_all_products, save_products, count_pending
from tools.llm import chat
from config import PINTEREST_ACCOUNTS

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ── Shared runtime state ───────────────────────────────────────────────────────
state = {
    "running":      False,
    "last_run":     None,
    "posted_today": 0,
    "last_summary": "Not run yet",
    "last_action":  "—",
    # Mastermind CEO state
    "mastermind_running":   False,
    "mastermind_last_run":  None,
    "mastermind_summary":   "Not run yet",
    "mastermind_a1_strategy": "—",
    "mastermind_a2_strategy": "—",
    "mastermind_a1_posted":   False,
    "mastermind_a2_posted":   False,
    "mastermind_fallback":    False,
}

scheduler = AsyncIOScheduler(timezone="America/New_York")


# ── Legacy agent scheduler ─────────────────────────────────────────────────────
async def scheduled_job(trigger: str):
    if state["running"]:
        logger.warning(f"⚠️ Agent already running. Skipping {trigger}")
        return
    state["running"] = True
    state["last_run"] = datetime.now().strftime("%H:%M")
    try:
        logger.info(f"🚀 Firing scheduled job: {trigger} (US EST)")
        result = await run_agent(trigger=trigger)
        state["last_summary"] = result.get("summary", "")
        state["posted_today"] += 1
    except Exception as e:
        state["last_summary"] = f"Error: {e}"
        logger.error(f"❌ Error in scheduled_job: {e}")
    finally:
        state["running"] = False


def schedule_random_pins():
    now = datetime.now()
    start_hour = 16
    window_minutes = 6 * 60

    for job in scheduler.get_jobs():
        if job.id and str(job.id).startswith("random_pin_"):
            scheduler.remove_job(job.id)

    logger.info("🎲 Generating 3 random pins each for Account 1 & Account 2 in US Prime Time...")
    for i in range(3):
        run_time = now.replace(hour=start_hour, minute=0, second=0, microsecond=0) + timedelta(minutes=random.randint(0, window_minutes))
        scheduler.add_job(scheduled_job, "date", run_date=run_time, id=f"random_pin_acc1_{i}", kwargs={"trigger": "scheduled-account1"})
        logger.info(f"📌 [Acc 1] Random Pin {i+1}: {run_time.strftime('%I:%M %p')} EST")
    for i in range(3):
        run_time = now.replace(hour=start_hour, minute=0, second=0, microsecond=0) + timedelta(minutes=random.randint(0, window_minutes))
        scheduler.add_job(scheduled_job, "date", run_date=run_time, id=f"random_pin_acc2_{i}", kwargs={"trigger": "scheduled-account2"})
        logger.info(f"📌 [Acc 2] Random Pin {i+1}: {run_time.strftime('%I:%M %p')} EST")


# ── Mastermind CEO scheduler ───────────────────────────────────────────────────
async def mastermind_scheduled_job(trigger: str = "scheduled-mastermind"):
    if state["mastermind_running"]:
        logger.warning(f"⚠️ Mastermind CEO already running. Skipping {trigger}")
        return
    state["mastermind_running"] = True
    state["mastermind_last_run"] = datetime.now().strftime("%H:%M")
    try:
        logger.info(f"🧠 Mastermind CEO cycle fired: {trigger}")
        result = await run_mastermind(trigger=trigger)
        state["mastermind_summary"]     = result.get("summary", "")
        state["mastermind_a1_strategy"] = result.get("a1_strategy", "—")
        state["mastermind_a2_strategy"] = result.get("a2_strategy", "—")
        state["mastermind_a1_posted"]   = result.get("a1_posted", False)
        state["mastermind_a2_posted"]   = result.get("a2_posted", False)
        state["mastermind_fallback"]    = result.get("fallback_triggered", False)
    except Exception as e:
        state["mastermind_summary"] = f"Mastermind Error: {e}"
        logger.error(f"❌ Mastermind scheduled job error: {e}")
    finally:
        state["mastermind_running"] = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Legacy fixed pins (unchanged) ────────────────────────────────────────
    scheduler.add_job(scheduled_job, "cron", hour=17, minute=0,  id="acc1_fixed_1", kwargs={"trigger": "scheduled-account1"})
    scheduler.add_job(scheduled_job, "cron", hour=20, minute=0,  id="acc1_fixed_2", kwargs={"trigger": "scheduled-account1"})
    scheduler.add_job(scheduled_job, "cron", hour=18, minute=0,  id="acc2_fixed_1", kwargs={"trigger": "scheduled-account2"})
    scheduler.add_job(scheduled_job, "cron", hour=21, minute=0,  id="acc2_fixed_2", kwargs={"trigger": "scheduled-account2"})
    scheduler.add_job(schedule_random_pins, "cron", hour=8, minute=0, id="daily_randomizer_trigger")

    # ── Mastermind CEO daily cycle at 9 AM EST (data analysis + strategic post) ─
    scheduler.add_job(mastermind_scheduled_job, "cron", hour=9, minute=0, id="mastermind_daily", kwargs={"trigger": "scheduled-mastermind"})

    schedule_random_pins()
    scheduler.start()
    logger.info("✅ Master Scheduler Active — US Time (EST) 🇺🇸")
    logger.info("🧠 Mastermind CEO Scheduler Active — daily at 9:00 AM EST")
    yield
    scheduler.shutdown()


app = FastAPI(title="Pinteresto Bot — Mastermind CEO", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def dashboard():
    return FileResponse("static/index.html")


# ── Stats ──────────────────────────────────────────────────────────────────────
@app.get("/api/stats")
async def get_stats():
    try:
        all_p   = get_all_products()
        pending = sum(1 for p in all_p if p.get("Status") == "PENDING")
        posted  = sum(1 for p in all_p if p.get("Status") == "POSTED")
        total   = len(all_p)
    except Exception:
        pending = posted = total = 0
    return {
        "pending":      pending,
        "posted":       posted,
        "total":        total,
        "posted_today": state["posted_today"],
        "last_run":     state["last_run"] or "Never",
        "last_summary": state["last_summary"],
        "last_action":  state["last_action"],
        "running":      state["running"],
    }


@app.get("/api/mastermind/stats")
async def get_mastermind_stats():
    return {
        "running":      state["mastermind_running"],
        "last_run":     state["mastermind_last_run"] or "Never",
        "summary":      state["mastermind_summary"],
        "a1_strategy":  state["mastermind_a1_strategy"],
        "a2_strategy":  state["mastermind_a2_strategy"],
        "a1_posted":    state["mastermind_a1_posted"],
        "a2_posted":    state["mastermind_a2_posted"],
        "fallback":     state["mastermind_fallback"],
    }


# ── Legacy agent endpoints (unchanged) ────────────────────────────────────────
def _bg_agent(background_tasks: BackgroundTasks, trigger: str, action_name: str):
    if state["running"]:
        return {"status": "busy", "message": "Agent already running"}
    async def _run():
        state["running"] = True
        state["last_run"] = datetime.now().strftime("%H:%M")
        state["last_action"] = action_name
        try:
            result = await run_agent(trigger=trigger)
            state["last_summary"] = result.get("summary", "")
            state["posted_today"] += 1
        except Exception as e:
            state["last_summary"] = f"Error: {e}"
        finally:
            state["running"] = False
    background_tasks.add_task(_run)
    return {"status": "started", "message": f"{action_name} started"}


@app.post("/api/run-agent")
async def trigger_agent(background_tasks: BackgroundTasks):
    return _bg_agent(background_tasks, "manual-api", "Full Agent Run")

@app.post("/api/run-account1")
async def trigger_account1(background_tasks: BackgroundTasks):
    return _bg_agent(background_tasks, "manual-account1", "Account 1 Pin")

@app.post("/api/run-account2")
async def trigger_account2(background_tasks: BackgroundTasks):
    return _bg_agent(background_tasks, "manual-account2", "Account 2 Pin")

@app.post("/api/fill-niches")
async def trigger_fill_niches(background_tasks: BackgroundTasks):
    if state["running"]:
        return {"status": "busy", "message": "Running"}
    async def _run():
        state["running"] = True
        state["last_action"] = "Fill Niches"
        try:
            result = await fill_missing_niches.ainvoke({})
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
        return {"status": "busy"}
    async def _run():
        state["running"] = True
        state["last_action"] = "Fetch Products"
        try:
            result = await fetch_aliexpress_products.ainvoke({"niche": "home"})
            state["last_summary"] = f"Fetched: {result.get('approved', 0)} approved"
        except Exception as e:
            state["last_summary"] = f"Fetch error: {e}"
        finally:
            state["running"] = False
    background_tasks.add_task(_run)
    return {"status": "started", "message": "Fetching products..."}


# ── Mastermind CEO endpoints ───────────────────────────────────────────────────
def _bg_mastermind(background_tasks: BackgroundTasks, trigger: str):
    if state["mastermind_running"]:
        return {"status": "busy", "message": "Mastermind CEO already running"}
    async def _run():
        state["mastermind_running"] = True
        state["mastermind_last_run"] = datetime.now().strftime("%H:%M")
        try:
            result = await run_mastermind(trigger=trigger)
            state["mastermind_summary"]     = result.get("summary", "")
            state["mastermind_a1_strategy"] = result.get("a1_strategy", "—")
            state["mastermind_a2_strategy"] = result.get("a2_strategy", "—")
            state["mastermind_a1_posted"]   = result.get("a1_posted", False)
            state["mastermind_a2_posted"]   = result.get("a2_posted", False)
            state["mastermind_fallback"]    = result.get("fallback_triggered", False)
        except Exception as e:
            state["mastermind_summary"] = f"Mastermind Error: {e}"
        finally:
            state["mastermind_running"] = False
    background_tasks.add_task(_run)
    return {"status": "started", "message": "Mastermind CEO pipeline started"}


@app.post("/api/mastermind/run")
async def mastermind_run(background_tasks: BackgroundTasks):
    """Trigger the full Mastermind CEO pipeline (both accounts)."""
    return _bg_mastermind(background_tasks, "manual-mastermind")


# ── Products endpoint ──────────────────────────────────────────────────────────
@app.get("/api/products")
async def get_products():
    try:
        all_p = get_all_products()
        return {"products": all_p}
    except Exception as e:
        logger.error(f"Error fetching products: {e}")
        return {"products": []}


# ── AI Chat ────────────────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    message: str
    history: list = []

@app.post("/api/chat")
async def ai_chat(msg: ChatMessage):
    try:
        context = (
            f"Running: {state['running']}, Action: {state['last_action']}, "
            f"Summary: {state['last_summary']}\n"
            f"Mastermind Running: {state['mastermind_running']}, "
            f"Mastermind Summary: {state['mastermind_summary']}"
        )
        history_text = "\n".join([
            f"{'User' if h.get('role') == 'user' else 'Assistant'}: {h.get('content', '')}"
            for h in msg.history[-4:]
        ])
        full_prompt = f"{context}\n\nChat:\n{history_text}\nUser: {msg.message}"
        response = chat(full_prompt, system="You are Pinteresto AI. Keep it short.", temperature=0.7)
        return {"response": response, "status": "ok"}
    except Exception:
        return {"response": "AI unavailable — configure API keys.", "status": "error"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
