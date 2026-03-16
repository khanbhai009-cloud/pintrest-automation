import logging
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from agent import run_agent
from tools.google_drive import get_all_products

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

state = {"running": False, "last_run": None, "posted_today": 0, "last_summary": "Not run yet"}
scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")

async def scheduled_job(trigger: str):
    if state["running"]:
        logger.warning("⚠️ Already running, skipping")
        return
    state["running"] = True
    state["last_run"] = datetime.now().strftime("%H:%M")
    try:
        result = await run_agent(trigger=trigger)
        state["last_summary"] = result.get("summary", "")
    except Exception as e:
        state["last_summary"] = f"Error: {e}"
        logger.error(f"❌ Job failed: {e}")
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

app = FastAPI(title="Pinterest Affiliate Bot", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def dashboard():
    return FileResponse("static/index.html")

@app.get("/api/stats")
async def get_stats():
    try:
        all_p   = get_all_products()
        pending = sum(1 for p in all_p if p.get("Status") == "PENDING")
        posted  = sum(1 for p in all_p if p.get("Status") == "POSTED")
        total   = len(all_p)
    except:
        pending = posted = total = 0
    return {
        "pending": pending, "posted": posted, "total": total,
        "posted_today": state["posted_today"], "last_run": state["last_run"] or "Never",
        "last_summary": state["last_summary"], "running": state["running"],
    }

@app.get("/api/products")
async def get_products():
    try:
        return {"products": get_all_products()}
    except Exception as e:
        return {"products": [], "error": str(e)}

@app.post("/api/run-agent")
async def trigger_agent(background_tasks: BackgroundTasks):
    if state["running"]:
        return {"status": "busy", "message": "Agent already running"}
    async def _run():
        state["running"] = True
        state["last_run"] = datetime.now().strftime("%H:%M")
        try:
            result = await run_agent(trigger="manual-api")
            state["last_summary"] = result.get("summary", "")
        except Exception as e:
            state["last_summary"] = f"Error: {e}"
        finally:
            state["running"] = False
    background_tasks.add_task(_run)
    return {"status": "started", "message": "Agent running in background"}

@app.get("/api/agent-status")
async def agent_status():
    return {"running": state["running"], "last_run": state["last_run"] or "Never", "last_summary": state["last_summary"]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
