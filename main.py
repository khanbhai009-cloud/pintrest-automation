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
from agent import run_agent
from tools.google_drive import get_all_products, save_products, count_pending
from tools.llm import chat

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

state = {
    "running": False, "last_run": None,
    "posted_today": 0, "last_summary": "Not run yet"
}
scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")

async def scheduled_job(trigger: str):
    if state["running"]:
        return
    state["running"] = True
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

app = FastAPI(title="Pinteresto Bot", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
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
        "posted_today": state["posted_today"],
        "last_run": state["last_run"] or "Never",
        "last_summary": state["last_summary"],
        "running": state["running"],
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
            state["posted_today"] += 1
        except Exception as e:
            state["last_summary"] = f"Error: {e}"
        finally:
            state["running"] = False
    background_tasks.add_task(_run)
    return {"status": "started", "message": "Agent running in background"}

@app.get("/api/agent-status")
async def agent_status():
    return {
        "running": state["running"],
        "last_run": state["last_run"] or "Never",
        "last_summary": state["last_summary"],
    }


# ── AI Chat endpoint ─────────────────────────────────────────
class ChatMessage(BaseModel):
    message: str
    history: list = []

CHAT_SYSTEM = """You are Pinteresto AI — a friendly assistant for an AliExpress Pinterest affiliate bot.
You help the owner manage their Pinterest automation business.

You have access to:
- Bot status (running/idle, last run, products posted)
- Google Sheets data (pending/posted products)
- Full bot control

You can:
1. Answer casual questions (haal chaal, kesi chal rhi business, etc.)
2. Generate Pinterest content (title, description, hashtags, emojis) for products
3. Suggest marketing strategies
4. Report on bot performance

Personality: Friendly, professional, mix of Hindi/English (Hinglish) ok.
Keep responses concise and helpful.

If user asks to post a pin or run the agent — tell them to use the "Run Agent" button or say you'll trigger it.
If user asks for hashtags/content — generate immediately, no questions asked.

Current bot: Pinterest Affiliate Bot — AliExpress products → Admitad links → Pinterest India audience."""

@app.post("/api/chat")
async def ai_chat(msg: ChatMessage):
    try:
        # Get live context
        try:
            products = get_all_products()
            pending  = sum(1 for p in products if p.get("Status") == "PENDING")
            posted   = sum(1 for p in products if p.get("Status") == "POSTED")
            recent   = [p.get("product_name","") for p in products[-3:]] if products else []
        except:
            pending = posted = 0
            recent  = []

        # Build context string
        context = f"""
Current bot status:
- Running: {state['running']}
- Last run: {state['last_run'] or 'Never'}
- Last summary: {state['last_summary']}
- Pending products: {pending}
- Posted products: {posted}
- Recent products: {', '.join(recent) if recent else 'None'}
"""
        # Build full prompt with history
        history_text = ""
        for h in msg.history[-6:]:  # last 6 messages for context
            role = "User" if h.get("role") == "user" else "Assistant"
            history_text += f"{role}: {h.get('content','')}\n"

        full_prompt = f"{context}\n\nConversation:\n{history_text}User: {msg.message}"

        response = chat(full_prompt, system=CHAT_SYSTEM, temperature=0.8)
        return {"response": response, "status": "ok"}

    except Exception as e:
        logger.error(f"Chat error: {e}")
        return {"response": "Kuch error aa gaya, dobara try karo!", "status": "error"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
