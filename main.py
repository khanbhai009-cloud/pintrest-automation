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

# 🔥 SABSE BADA CHANGE: Timezone ab US Eastern Time (New York) ho gaya hai!
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
    start_hour = 16  # US ke Dopehar 4:00 PM se window shuru
    window_minutes = 6 * 60  # 6 ghante ki window (10:00 PM tak)
    
    # Pehle purane random jobs clear karo taaki duplicate na bane
    for job in scheduler.get_jobs():
        if job.id and str(job.id).startswith("random_pin_"):
            scheduler.remove_job(job.id)
            
    logger.info("🎲 Generating 3 Random pins for Account 1 AND 3 for Account 2 in US Prime Time...")

    # 🟢 Account 1 ke liye 3 random pins
    for i in range(3):
        random_mins = random.randint(0, window_minutes)
        run_time = now.replace(hour=start_hour, minute=0, second=0, microsecond=0) + timedelta(minutes=random_mins)
        scheduler.add_job(
            scheduled_job, "date", run_date=run_time, 
            id=f"random_pin_acc1_{i}", kwargs={"trigger": "scheduled-account1"}
        )
        logger.info(f"📌 [Acc 1] Random Pin {i+1} Set: {run_time.strftime('%I:%M %p')} EST")

    # 🔵 Account 2 ke liye 3 random pins
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
    # ---------------------------------------------------------
    # 1️⃣ FIXED PINS (US EST TIME KE HISAAB SE)
    # ---------------------------------------------------------
    # Account 1 Fixed: US Shaam 5:00 PM (17:00) & Raat 8:00 PM (20:00)
    scheduler.add_job(scheduled_job, "cron", hour=17, minute=0, id="acc1_fixed_1", kwargs={"trigger": "scheduled-account1"})
    scheduler.add_job(scheduled_job, "cron", hour=20, minute=0, id="acc1_fixed_2", kwargs={"trigger": "scheduled-account1"})
    
    # Account 2 Fixed: US Shaam 6:00 PM (18:00) & Raat 9:00 PM (21:00)
    scheduler.add_job(scheduled_job, "cron", hour=18, minute=0, id="acc2_fixed_1", kwargs={"trigger": "scheduled-account2"})
    scheduler.add_job(scheduled_job, "cron", hour=21, minute=0, id="acc2_fixed_2", kwargs={"trigger": "scheduled-account2"})
    
    # ---------------------------------------------------------
    # 2️⃣ RANDOM PINS SETUP
    # ---------------------------------------------------------
    # Ye job daily US subah 8 baje chalega aur aaj ke random time decide karega
    scheduler.add_job(schedule_random_pins, "cron", hour=8, minute=0, id="daily_randomizer_trigger")
    
    # Server start hote hi aaj ke liye random pins activate kar dete hain
    schedule_random_pins()

    scheduler.start()
    logger.info("✅ Master Scheduler Active — Bot ab pure US Time (EST) par chal raha hai! 🇺🇸")
    yield
    scheduler.shutdown()

# FastAPI App setup
app = FastAPI(title="Pinteresto Bot", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def dashboard(): return FileResponse("static/index.html")

@app.get("/api/ping")
async def ping(): return {"status": "ok", "message": "pong"}

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

@app.get("/api/products")
async def get_products():
    try: return {"products": get_all_products()}
    except Exception as e: return {"products": [], "error": str(e)}

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
    if state["running"]: return {"status": "busy"}
    async def _run():
        state["running"] = True
        state["last_action"] = "Fetch Products"
        try:
            result = await fetch_aliexpress_products.func(niche="home")
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

if __name__ == "__main__":
    import uvicorn
    # Terminal me run karke dekho, sidha start hoga aur dashboard live!
    uvicorn.run(app, host="0.0.0.0", port=7860)
