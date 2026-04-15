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

# Mastermind aur Tools imports
from agent import run_agent, fill_missing_niches, fetch_aliexpress_products
from mastermind.graph import run_mastermind
from tools.google_drive import get_all_products
from tools.llm import chat

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

state = {
    "running": False, "last_run": None, "posted_today": 0, "last_summary": "Not run yet",
    "mastermind_running": False, "mastermind_last_run": None, "mastermind_summary": "Not run yet"
}

scheduler = AsyncIOScheduler(timezone="America/New_York")

# ── Mastermind Executer ───────────────────────────────────────────────────────
async def mastermind_scheduled_job(trigger: str):
    if state["mastermind_running"]:
        logger.warning(f"⚠️ Mastermind already running. Skipping {trigger}")
        return
    state["mastermind_running"] = True
    state["mastermind_last_run"] = datetime.now().strftime("%H:%M")
    try:
        logger.info(f"🧠 Mastermind Triggered: {trigger}")
        result = await run_mastermind(trigger=trigger)
        state["mastermind_summary"] = result.get("summary", "Done")
    except Exception as e:
        logger.error(f"❌ Mastermind Error: {e}")
    finally:
        state["mastermind_running"] = False

# ── Random Scheduler Logic (3 Pins Each) ──────────────────────────────────────
def schedule_random_pins():
    now = datetime.now()
    
    # Purane random jobs saaf karo
    for job in scheduler.get_jobs():
        if job.id.startswith("random_"): scheduler.remove_job(job.id)

    # Account 1 (Home Decor): 10:00 AM se 4:00 PM ke beech 3 random pins
    a1_start = 10
    for i in range(3):
        # 6 ghante ki window (360 mins)
        run_time = now.replace(hour=a1_start, minute=0, second=0, microsecond=0) + timedelta(minutes=random.randint(0, 360))
        if run_time > now:
            scheduler.add_job(mastermind_scheduled_job, "date", run_date=run_time, id=f"random_a1_{i}", kwargs={"trigger": "scheduled-account1"})
            logger.info(f"📌 [Acc 1] Slot {i+1} set at: {run_time.strftime('%I:%M %p')} EST")

    # Account 2 (Tech): 7:00 PM se 1:00 AM ke beech 3 random pins
    a2_start = 19
    for i in range(3):
        # 6 ghante ki window (360 mins)
        run_time = now.replace(hour=a2_start, minute=0, second=0, microsecond=0) + timedelta(minutes=random.randint(0, 360))
        if run_time > now:
            scheduler.add_job(mastermind_scheduled_job, "date", run_date=run_time, id=f"random_a2_{i}", kwargs={"trigger": "scheduled-account2"})
            logger.info(f"📌 [Acc 2] Slot {i+1} set at: {run_time.strftime('%I:%M %p')} EST")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Har roz subah 8 baje naye random slots generate honge
    scheduler.add_job(schedule_random_pins, "cron", hour=8, minute=0, id="daily_randomizer")
    
    # Pehli baar run karne par turant schedule kar do
    schedule_random_pins()
    
    scheduler.start()
    logger.info("✅ Mastermind Random Scheduler Active (3+3 Pins per day)")
    yield
    scheduler.shutdown()

app = FastAPI(title="Pinteresto Mastermind", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def dashboard(): return FileResponse("static/index.html")

@app.get("/api/mastermind/stats")
async def get_stats():
    return {
        "running": state["mastermind_running"],
        "last_run": state["mastermind_last_run"] or "Never",
        "summary": state["mastermind_summary"]
    }

# Manual Trigger Buttons
@app.post("/api/run-account1")
async def run_a1(background_tasks: BackgroundTasks):
    background_tasks.add_task(mastermind_scheduled_job, "manual-account1")
    return {"status": "started"}

@app.post("/api/run-account2")
async def run_a2(background_tasks: BackgroundTasks):
    background_tasks.add_task(mastermind_scheduled_job, "manual-account2")
    return {"status": "started"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
