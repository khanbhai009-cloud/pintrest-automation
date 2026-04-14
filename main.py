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

# Tumhare custom imports
from agent import run_agent, fill_missing_niches, fetch_aliexpress_products, publish_next_pin
from tools.google_drive import get_all_products, save_products, count_pending
from tools.llm import chat
from config import PINTEREST_ACCOUNTS

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

state = {
    "running": False, "last_run": None,
    "posted_today": 0, "last_summary": "Not run yet", "last_action": "—",
}

# Timezone US Eastern Time (New York)
scheduler = AsyncIOScheduler(timezone="America/New_York")

async def scheduled_job(trigger: str):
    """Core function jo bot ko chalayega"""
    if state["running"]: 
        logger.warning(f"⚠️ Agent is already running. Skipping {trigger}")
        return
        
    state["running"] = True
    state["last_run"] = datetime.now().strftime("%H:%M")
    try:
        logger.info(f"🚀 Firing scheduled job: {trigger} (US Time)")
        result = await run_agent(trigger=trigger)
        state["last_summary"] = result.get("summary", "")
        state["posted_today"] += 1
    except Exception as e:
        state["last_summary"] = f"Error: {e}"
        logger.error(f"❌ Error in scheduled_job: {e}")
    finally:
        state["running"] = False

def schedule_random_pins():
    """US Prime Time (4 PM se 10 PM) ke beech random pins generate karega"""
    now = datetime.now()
    start_hour = 16 
    window_minutes = 6 * 60 
    
    for job in scheduler.get_jobs():
        if job.id and str(job.id).startswith("random_pin_"):
            scheduler.remove_job(job.id)
            
    logger.info("🎲 Generating 3 Random pins for Account 1 AND 3 for Account 2 in US Prime Time...")

    for i in range(3):
        random_mins = random.randint(0, window_minutes)
        run_time = now.replace(hour=start_hour, minute=0, second=0, microsecond=0) + timedelta(minutes=random_mins)
        scheduler.add_job(
            scheduled_job, "date", run_date=run_time, 
            id=f"random_pin_acc1_{i}", kwargs={"trigger": "scheduled-account1"}
        )
        logger.info(f"📌 [Acc 1] Random Pin {i+1} Set: {run_time.strftime('%I:%M %p')} EST")

    for i in range(3):
        random_mins = random.randint(0, window_minutes)
        run_time = now.replace(hour=start_hour, minute=0, second=0, microsecond=0) + timedelta(minutes=random_mins)
        scheduler.add_job(
            scheduled_job, "date", run_date=run_time, 
            id=f"random_pin_acc2_{i}", kwargs={"trigger": "scheduled-account2"}
        )
        logger.info(f"📌 [Acc 2] Random Pin {i+1} Set: {run_time.strftime('%I:%M %p')} EST")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # FIXED PINS (US EST)
    scheduler.add_job(scheduled_job, "cron", hour=17, minute=0, id="acc1_fixed_1", kwargs={"trigger": "scheduled-account1"})
    scheduler.add_job(scheduled_job, "cron", hour=20, minute=0, id="acc1_fixed_2", kwargs={"trigger": "scheduled-account1"})
    
    scheduler.add_job(scheduled_job, "cron", hour=18, minute=0, id="acc2_fixed_1", kwargs={"trigger": "scheduled-account2"})
    scheduler.add_job(scheduled_job, "cron", hour=21, minute=0, id="acc2_fixed_2", kwargs={"trigger": "scheduled-account2"})
    
    scheduler.add_job(schedule_random_pins, "cron", hour=8, minute=0, id="daily_randomizer_trigger")
    
    schedule_random_pins()
    scheduler.start()
    logger.info("✅ Master Scheduler Active — US Time (EST) 🇺🇸")
    yield
    scheduler.shutdown()

app = FastAPI(title="Pinteresto Bot", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def dashboard(): return FileResponse("static/index.html")

@app.get("/api/stats")
async def get_stats():
    try:
        all_p = get_all_products()
        pending = sum(1 for p in all_p if p.get("Status") == "PENDING")
        posted = sum(1 for p in all_p if p.get("Status") == "POSTED")
        total = len(all_p)
    except:
        pending = posted = total = 0
    return {
        "pending": pending, "posted": posted, "total": total,
        "posted_today": state["posted_today"], "last_run": state["last_run"] or "Never",
        "last_summary": state["last_summary"], "last_action": state["last_action"],
        "running": state["running"]
    }

def bg_task_runner(background_tasks: BackgroundTasks, trigger: str, action_name: str):
    if state["running"]: return {"status": "busy", "message": "Agent already running"}
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
    return bg_task_runner(background_tasks, "manual-api", "Full Agent Run")

@app.post("/api/run-account1")
async def trigger_account1(background_tasks: BackgroundTasks):
    return bg_task_runner(background_tasks, "manual-account1", "Account 1 Pin")

@app.post("/api/run-account2")
async def trigger_account2(background_tasks: BackgroundTasks):
    return bg_task_runner(background_tasks, "manual-account2", "Account 2 Pin")

@app.post("/api/fill-niches")
async def trigger_fill_niches(background_tasks: BackgroundTasks):
    if state["running"]: return {"status": "busy", "message": "Running"}
    async def _run():
        state["running"] = True
        state["last_action"] = "Fill Niches"
        try:
            # ✅ FIX: Using ainvoke instead of .func()
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
    if state["running"]: return {"status": "busy"}
    async def _run():
        state["running"] = True
        state["last_action"] = "Fetch Products"
        try:
            # ✅ FIX: Using ainvoke instead of .func()
            result = await fetch_aliexpress_products.ainvoke({"niche": "home"})
            state["last_summary"] = f"Fetched: {result.get('approved',0)} approved"
        except Exception as e:
            state["last_summary"] = f"Fetch error: {e}"
        finally:
            state["running"] = False
    background_tasks.add_task(_run)
    return {"status": "started", "message": "Fetching products..."}

class ChatMessage(BaseModel):
    message: str
    history: list = []

@app.post("/api/chat")
async def ai_chat(msg: ChatMessage):
    try:
        context = f"Running: {state['running']}, Action: {state['last_action']}, Summary: {state['last_summary']}"
        history_text = "\n".join([f"{'User' if h.get('role')=='user' else 'Assistant'}: {h.get('content','')}" for h in msg.history[-4:]])
        full_prompt = f"{context}\n\nChat:\n{history_text}\nUser: {msg.message}"
        response = chat(full_prompt, system="You are Pinteresto AI. Keep it short.", temperature=0.7)
        return {"response": response, "status": "ok"}
    except Exception:
        return {"response": "Kuch error aaya bhai!", "status": "error"}

@app.get("/api/products")
async def get_products():
    try:
        all_p = get_all_products()
        return {"products": all_p}
    except Exception as e:
        logger.error(f"Error fetching products: {e}")
        return {"products": []}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
