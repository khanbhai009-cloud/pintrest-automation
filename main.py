import asyncio
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from phases.phase1_filter import run_filter_bot
from phases.phase2_publish import run_publisher_bot
from phases.phase3_refill import check_and_refill
from tools.google_drive import count_pending, get_all_products

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

state = {"running": False, "last_run": None, "posted_today": 0}
scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")

async def daily_job():
    state["running"] = True
    state["last_run"] = datetime.now().strftime("%H:%M")
    logger.info("=" * 50)
    logger.info("🚀 Daily Job Started")
    try:
        await check_and_refill()
        posted = await run_publisher_bot()
        state["posted_today"] = posted
    finally:
        state["running"] = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(daily_job, "cron", hour=9, minute=0)
    scheduler.start()
    logger.info("✅ Scheduler started — Bot is live!")
    yield
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def dashboard():
    return FileResponse("static/index.html")

@app.get("/api/stats")
async def get_stats():
    try:
        all_p = get_all_products()
        pending = sum(1 for p in all_p if p.get("Status") == "PENDING")
        total = len(all_p)
    except:
        pending = total = 0
    return {
        "pending": pending,
        "total": total,
        "posted_today": state["posted_today"],
        "last_run": state["last_run"] or "Never",
        "running": state["running"]
    }

@app.get("/api/products")
async def get_products():
    try:
        return {"products": get_all_products()}
    except Exception as e:
        return {"products": [], "error": str(e)}

@app.post("/api/run/{phase}")
async def run_phase(phase: str):
    try:
        if phase == "1":
            result = await run_filter_bot()
            return {"status": "ok", "message": f"{len(result)} products approved"}
        elif phase == "2":
            result = await run_publisher_bot()
            state["posted_today"] += result
            return {"status": "ok", "message": f"{result} pins posted"}
        elif phase == "3":
            await check_and_refill()
            return {"status": "ok", "message": "Refill check done"}
        elif phase == "all":
            await check_and_refill()
            result = await run_publisher_bot()
            state["posted_today"] += result
            return {"status": "ok", "message": f"Full run done, {result} pins posted"}
        else:
            return {"status": "error", "message": "Invalid phase"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
