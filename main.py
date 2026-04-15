import asyncio
import logging
import random
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import BaseModel

from agent import run_agent, fill_missing_niches, fetch_aliexpress_products
from mastermind.graph import run_mastermind
from tools.google_drive import get_all_products
from tools.llm import chat

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ── Global State ──────────────────────────────────────────────────────────────
state = {
    "running": False,
    "last_run": None,
    "posted_today": 0,
    "last_summary": "Not run yet",
    "mastermind_running": False,
    "mastermind_last_run": None,
    "mastermind_summary": "Awaiting first cycle...",
    "mastermind_a1_strategy": "—",
    "mastermind_a2_strategy": "—",
    "mastermind_a1_posted": False,
    "mastermind_a2_posted": False,
    "mastermind_fallback": False,
    "stop_requested": False,
}

scheduler = AsyncIOScheduler(timezone="America/New_York")

# ── Mastermind Job ─────────────────────────────────────────────────────────────
async def mastermind_scheduled_job(trigger: str):
    if state["mastermind_running"]:
        logger.warning(f"⚠️ Mastermind already running. Skipping {trigger}")
        return
    state["mastermind_running"] = True
    state["stop_requested"] = False
    state["mastermind_last_run"] = datetime.now().strftime("%H:%M")
    try:
        logger.info(f"🧠 Mastermind Triggered: {trigger}")
        result = await run_mastermind(trigger=trigger)
        state["mastermind_summary"]    = result.get("summary", "Done")
        state["mastermind_a1_strategy"] = result.get("a1_strategy", "—")
        state["mastermind_a2_strategy"] = result.get("a2_strategy", "—")
        state["mastermind_a1_posted"]   = result.get("a1_posted", False)
        state["mastermind_a2_posted"]   = result.get("a2_posted", False)
        state["mastermind_fallback"]    = result.get("fallback_triggered", False)
        state["posted_today"] += (1 if result.get("a1_posted") else 0) + (1 if result.get("a2_posted") else 0)
    except Exception as e:
        logger.error(f"❌ Mastermind Error: {e}")
        state["mastermind_summary"] = f"Error: {e}"
    finally:
        state["mastermind_running"] = False

# ── Random Scheduler ───────────────────────────────────────────────────────────
def schedule_random_pins():
    now = datetime.now()
    for job in scheduler.get_jobs():
        if job.id.startswith("random_"):
            scheduler.remove_job(job.id)

    for i in range(3):
        rt = now.replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(minutes=random.randint(0, 360))
        if rt > now:
            scheduler.add_job(mastermind_scheduled_job, "date", run_date=rt,
                               id=f"random_a1_{i}", kwargs={"trigger": "scheduled-account1"})
            logger.info(f"📌 [Acc 1] Slot {i+1}: {rt.strftime('%I:%M %p')} EST")

    for i in range(3):
        rt = now.replace(hour=19, minute=0, second=0, microsecond=0) + timedelta(minutes=random.randint(0, 360))
        if rt > now:
            scheduler.add_job(mastermind_scheduled_job, "date", run_date=rt,
                               id=f"random_a2_{i}", kwargs={"trigger": "scheduled-account2"})
            logger.info(f"📌 [Acc 2] Slot {i+1}: {rt.strftime('%I:%M %p')} EST")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(schedule_random_pins, "cron", hour=8, minute=0, id="daily_randomizer")
    schedule_random_pins()
    scheduler.start()
    logger.info("✅ Mastermind Random Scheduler Active (3+3 Pins/day)")
    yield
    scheduler.shutdown()

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Pinteresto Mastermind", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def dashboard():
    return FileResponse("static/index.html")

# ── Stats ──────────────────────────────────────────────────────────────────────
@app.get("/api/stats")
async def get_all_stats():
    try:
        products = get_all_products()
        pending = sum(1 for p in products if p.get("Status") == "PENDING")
        posted  = sum(1 for p in products if p.get("Status") == "POSTED")
        total   = len(products)
    except Exception:
        pending = posted = total = 0
    return {
        "running":      state["running"],
        "pending":      pending,
        "posted":       posted,
        "total":        total,
        "posted_today": state["posted_today"],
        "last_action":  state["last_run"] or "—",
        "last_summary": state["last_summary"],
    }

# ── Mastermind Stats ───────────────────────────────────────────────────────────
@app.get("/api/mastermind/stats")
async def get_mastermind_stats():
    jobs = scheduler.get_jobs()
    scheduled_slots = [
        {"id": j.id, "next_run": j.next_run_time.strftime("%I:%M %p EST") if j.next_run_time else "—"}
        for j in jobs if j.id.startswith("random_")
    ]
    return {
        "running":      state["mastermind_running"],
        "last_run":     state["mastermind_last_run"] or "Never",
        "summary":      state["mastermind_summary"],
        "a1_strategy":  state["mastermind_a1_strategy"],
        "a2_strategy":  state["mastermind_a2_strategy"],
        "a1_posted":    state["mastermind_a1_posted"],
        "a2_posted":    state["mastermind_a2_posted"],
        "fallback":     state["mastermind_fallback"],
        "scheduled_slots": scheduled_slots,
    }

# ── Products ───────────────────────────────────────────────────────────────────
@app.get("/api/products")
async def get_products():
    try:
        products = get_all_products()
        return {"products": products[:50]}
    except Exception as e:
        return {"products": [], "error": str(e)}

# ── Mastermind Run / Stop ──────────────────────────────────────────────────────
@app.post("/api/mastermind/run")
async def run_mastermind_api(background_tasks: BackgroundTasks):
    if state["mastermind_running"]:
        return {"status": "busy", "message": "Mastermind already running!"}
    background_tasks.add_task(mastermind_scheduled_job, "manual-both")
    return {"status": "started"}

@app.post("/api/mastermind/run-account1")
async def run_mm_a1(background_tasks: BackgroundTasks):
    if state["mastermind_running"]:
        return {"status": "busy"}
    background_tasks.add_task(mastermind_scheduled_job, "manual-account1")
    return {"status": "started"}

@app.post("/api/mastermind/run-account2")
async def run_mm_a2(background_tasks: BackgroundTasks):
    if state["mastermind_running"]:
        return {"status": "busy"}
    background_tasks.add_task(mastermind_scheduled_job, "manual-account2")
    return {"status": "started"}

@app.post("/api/mastermind/stop")
async def stop_mastermind():
    state["stop_requested"] = True
    return {"status": "stop_requested", "message": "Stop signal sent. Current cycle will finish gracefully."}

# ── Account Triggers (legacy + new) ───────────────────────────────────────────
@app.post("/api/run-account1")
async def run_a1(background_tasks: BackgroundTasks):
    if state["mastermind_running"]:
        return {"status": "busy"}
    background_tasks.add_task(mastermind_scheduled_job, "manual-account1")
    return {"status": "started"}

@app.post("/api/run-account2")
async def run_a2(background_tasks: BackgroundTasks):
    if state["mastermind_running"]:
        return {"status": "busy"}
    background_tasks.add_task(mastermind_scheduled_job, "manual-account2")
    return {"status": "started"}

@app.post("/api/stop")
async def stop_all():
    state["stop_requested"] = True
    state["running"] = False
    return {"status": "stop_requested"}

# ── Utilities ──────────────────────────────────────────────────────────────────
@app.post("/api/fetch-products")
async def fetch_products_api(background_tasks: BackgroundTasks):
    async def _fetch():
        try:
            result = await fetch_aliexpress_products.ainvoke({"niche": "home"})
            state["last_summary"] = f"Fetched: {result.get('approved', 0)} products approved"
        except Exception as e:
            state["last_summary"] = f"Fetch error: {e}"
    background_tasks.add_task(_fetch)
    return {"status": "started", "message": "Fetching products..."}

@app.post("/api/fill-niches")
async def fill_niches_api(background_tasks: BackgroundTasks):
    async def _fill():
        try:
            result = fill_missing_niches.invoke({})
            state["last_summary"] = result.get("message", "Niches filled")
        except Exception as e:
            state["last_summary"] = f"Niche fill error: {e}"
    background_tasks.add_task(_fill)
    return {"status": "started", "message": "Filling niches..."}

# ── AI Chat Interface ──────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    message: str

CHAT_SYSTEM_PROMPT = """Tu PINTERESTO hai — "Finisher Tech AI" ka AI assistant jo Pinterest automation empire manage karta hai.
Tu Hinglish (Hindi + English mix) mein baat karta hai. Tu confident, smart aur helpful hai.

SYSTEM KI JANKARI:
- 2 Pinterest accounts hain: Account1 (HomeDecor niches: home, kitchen, cozy, gadgets, organize) aur Account2 (Tech niches: tech, budget, phone, smarthome, wfh)
- Mastermind CMO: Gemini 1.5 analytics dekh ke strategy decide karta hai (Visual Pivot, Viral-Bait, Aggressive Affiliate Strike)
- Visual Pivot / Viral-Bait: T2I image — Pollinations → Puter fallback — affiliate link strip
- Aggressive Affiliate Strike: I2I image via Puter — affiliate link rakho
- Images ImgBB pe upload hoti hain (30 min temp URL), phir Make.com webhook se Pinterest pe jaati hain
- Products Amazon se RapidAPI ke through aate hain, Google Sheet mein store hote hain

COMMANDS JO TU DETECT KARTA HAI (lowercase dekh):
- "aesthetic pin", "visual pin", "vibe pin" → action: run_aesthetic
- "product pin", "affiliate pin", "money pin" → action: run_product  
- "account 1", "home decor", "acc1" → action: run_acc1
- "account 2", "tech", "acc2" → action: run_acc2
- "mastermind", "cmo", "gemini" → action: run_mastermind
- "status", "kesa hai", "kaisa hai", "update" → action: get_status
- "stop", "rok do", "band karo" → action: stop
- "products fetch", "naye products" → action: fetch_products

Agar command detect ho, response ke END mein likho: [ACTION:action_name]
Warna normal baat kar.

RESPONSE RULES:
- Max 3-4 sentences, crisp aur confident
- Hinglish mein — mix of Hindi aur English natural lagni chahiye
- Emojis use kar lekin overdo mat kar
- Technical details briefly dena, jyada detail avoid"""

@app.post("/api/chat")
async def chat_endpoint(req: ChatMessage, background_tasks: BackgroundTasks):
    msg = req.message.strip()
    if not msg:
        return {"response": "Kuch toh pooch yaar! 😄", "action": None}

    msg_lower = msg.lower()

    # Determine system context for AI
    sys_ctx = (
        f"Current system state: Mastermind {'RUNNING' if state['mastermind_running'] else 'IDLE'}. "
        f"Last run: {state['mastermind_last_run'] or 'Never'}. "
        f"A1 strategy: {state['mastermind_a1_strategy']}. "
        f"A2 strategy: {state['mastermind_a2_strategy']}. "
        f"Today posted: {state['posted_today']} pins."
    )

    full_prompt = f"{CHAT_SYSTEM_PROMPT}\n\n{sys_ctx}\n\nUser: {msg}"

    action = None
    action_msg = ""

    # Execute detected action in background
    async def _do_action(act: str):
        if act == "run_mastermind" or act == "run_aesthetic" or act == "run_product":
            await mastermind_scheduled_job("manual-both")
        elif act == "run_acc1":
            await mastermind_scheduled_job("manual-account1")
        elif act == "run_acc2":
            await mastermind_scheduled_job("manual-account2")
        elif act == "fetch_products":
            try:
                await fetch_aliexpress_products.ainvoke({"niche": "home"})
            except Exception:
                pass
        elif act == "stop":
            state["stop_requested"] = True

    try:
        import asyncio
        ai_response = await asyncio.to_thread(chat, full_prompt, 0.75)

        # Extract action tag from response
        if "[ACTION:" in ai_response:
            parts = ai_response.split("[ACTION:")
            ai_response = parts[0].strip()
            action = parts[1].replace("]", "").strip()
            if not state["mastermind_running"] or action == "stop":
                background_tasks.add_task(_do_action, action)
                action_msg = f" (Action triggered: {action})"

    except Exception as e:
        logger.error(f"Chat LLM error: {e}")
        ai_response = "Bhai, abhi LLM se baat nahi ho pa rahi. Thodi der baad try karo! 🙏"

    return {
        "response": ai_response,
        "action": action,
        "action_msg": action_msg,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
