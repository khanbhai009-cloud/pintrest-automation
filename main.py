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
from config import GEMINI_API_KEY

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ── Gemini Client (for CMO chat) ───────────────────────────────────────────────
try:
    from google import genai as _genai
    _gemini_client = _genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
except Exception:
    _gemini_client = None

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

# ── Smart Daily Scheduler ──────────────────────────────────────────────────────
#
# Window : India 6 PM → 6 AM next day  =  EST 7:30 AM → 7:30 PM  (12 hours)
# Pins   : 10 total per day — 5 per account
# Gap    : min 25 min between ANY two consecutive pins (no parallel posting)
# Layout : slots interleaved  →  A1, A2, A1, A2, A1, A2, A1, A2, A1, A2
# Split  : each account randomly gets 2 VIRAL + 3 AFFILIATE  OR  3 VIRAL + 2 AFFILIATE
#
# Trigger string format: "scheduled-account1-VIRAL_PIN"
#   → CMO reads account + pin_type override from trigger
#   → Agent Executor posts ONLY the specified account
#
# Best USA Pinterest times (EST):
#   8:00–11:00 AM  (morning browse peak)
#   2:00–4:00 PM   (afternoon peak)
#   6:00–7:30 PM   (early evening — end of our window)
#
# ─────────────────────────────────────────────────────────────────────────────

def _random_daily_split() -> list:
    """Return a shuffled list of 5 pin types — randomly 2+3 or 3+2 VIRAL/AFFILIATE."""
    viral_count = random.choice([2, 3])
    types = ["VIRAL_PIN"] * viral_count + ["AFFILIATE_PIN"] * (5 - viral_count)
    random.shuffle(types)
    return types


def schedule_daily_pins():
    """
    Generate and register today's 10-pin schedule.
    Called once at startup and again via daily cron at 7:00 AM EST.
    """
    tz  = scheduler.timezone
    now = datetime.now(tz=tz)

    def _make_dt(d, h, m):
        """Create a timezone-aware datetime — works with both pytz and zoneinfo."""
        naive = datetime(d.year, d.month, d.day, h, m, 0)
        try:
            return tz.localize(naive)          # pytz
        except AttributeError:
            return naive.replace(tzinfo=tz)    # zoneinfo

    # ── Build window for today ─────────────────────────────────────────────────
    today        = now.date()
    window_start = _make_dt(today, 7, 30)
    window_end   = _make_dt(today, 19, 30)

    # If we're already past the window, schedule for tomorrow
    if now >= window_end:
        tomorrow     = today + timedelta(days=1)
        window_start = _make_dt(tomorrow, 7, 30)
        window_end   = _make_dt(tomorrow, 19, 30)

    WINDOW_MINUTES = 720   # 7:30 AM → 7:30 PM = 12 hours
    MIN_GAP        = 25    # minimum gap (minutes) between any two consecutive pin slots

    # ── Generate 10 time slots with min gap enforced ───────────────────────────
    slots = []
    for _ in range(20_000):
        if len(slots) == 10:
            break
        candidate = random.randint(0, WINDOW_MINUTES - 1)
        if all(abs(candidate - s) >= MIN_GAP for s in slots):
            slots.append(candidate)
    slots.sort()

    # ── Random pin-type split for each account ─────────────────────────────────
    a1_plan = _random_daily_split()   # e.g. ["VIRAL_PIN", "AFFILIATE_PIN", ...]
    a2_plan = _random_daily_split()

    # ── Remove old scheduled pin jobs ─────────────────────────────────────────
    for job in scheduler.get_jobs():
        if job.id.startswith("pin_"):
            scheduler.remove_job(job.id)

    # ── Register jobs — interleaved A1/A2 ──────────────────────────────────────
    a1_idx = a2_idx = scheduled = 0

    for i, offset_min in enumerate(slots):
        run_time = window_start + timedelta(minutes=offset_min)
        if run_time <= now:
            continue   # slot already in the past — skip

        if i % 2 == 0 and a1_idx < 5:         # even slot → Account 1
            pin_type = a1_plan[a1_idx]
            scheduler.add_job(
                mastermind_scheduled_job, "date", run_date=run_time,
                id=f"pin_a1_{a1_idx + 1}",
                kwargs={"trigger": f"scheduled-account1-{pin_type}"},
            )
            logger.info(f"📌 [Acc1 #{a1_idx+1}] {run_time.strftime('%I:%M %p')} EST → {pin_type}")
            a1_idx   += 1
            scheduled += 1

        elif i % 2 == 1 and a2_idx < 5:       # odd slot  → Account 2
            pin_type = a2_plan[a2_idx]
            scheduler.add_job(
                mastermind_scheduled_job, "date", run_date=run_time,
                id=f"pin_a2_{a2_idx + 1}",
                kwargs={"trigger": f"scheduled-account2-{pin_type}"},
            )
            logger.info(f"📌 [Acc2 #{a2_idx+1}] {run_time.strftime('%I:%M %p')} EST → {pin_type}")
            a2_idx   += 1
            scheduled += 1

    logger.info(
        f"✅ Daily schedule ready — {scheduled}/10 pins registered\n"
        f"   Acc1 plan ({a1_idx} slots): {a1_plan}\n"
        f"   Acc2 plan ({a2_idx} slots): {a2_plan}\n"
        f"   Window: {window_start.strftime('%I:%M %p')} → {window_end.strftime('%I:%M %p')} EST"
    )
    # Reset daily counter
    state["posted_today"] = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Daily re-scheduler — fires at 7:00 AM EST (30 min before window opens)
    scheduler.add_job(schedule_daily_pins, "cron", hour=7, minute=0, id="daily_scheduler")
    schedule_daily_pins()
    scheduler.start()
    logger.info("✅ Smart Scheduler Active — 10 pins/day (5 per account) in EST 7:30 AM–7:30 PM window")
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
        ai_response = await asyncio.to_thread(chat, full_prompt, temperature=0.75)

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

# ── CEO Mastermind Chat (Gemini) ───────────────────────────────────────────────
CMO_SYSTEM_PROMPT = """You are the CEO MASTERMIND of "Pinteresto — Finisher Tech AI", a fully autonomous Pinterest marketing empire.
You are a strategic genius who thinks like a top-tier CMO. You speak in a friendly, confident, slightly bold style — like a smart business friend who knows Pinterest inside out.
Mix English with a little Hinglish when it feels natural, but keep it professional and sharp.

YOUR KNOWLEDGE BASE:
- System runs 6 pins/day across 2 Pinterest accounts (3 pins each via scheduled automation)
- Account 1: HomeDecor niches — home, kitchen, cozy, organize, gadgets
- Account 2: Tech niches — tech, budget, phone, smarthome, wfh
- Pin routing: 70% VIRAL_PIN (AI-generated T2I image, strip affiliate link for clean viral reach) / 30% AFFILIATE_PIN (raw product image, keep affiliate link for direct revenue)
- Image generation: Gemini 2.5 Flash Image (primary, 9:16 portrait) → Puter.js free tier (fallback)
- CMO Brain: Gemini 2.5 Flash Lite reads analytics → decides strategy → writes title, description, tags, visual_prompt
- Strategies: Visual Pivot, Viral-Bait, Aggressive Affiliate Strike, Niche Authority Play
- LLM Stack: Groq Llama 3.3 70B (primary execution agent) → Cerebras fallback
- Products: Amazon via RapidAPI → filtered by quality → stored in Google Sheets
- Delivery: ImgBB temp hosting → Make.com webhook → Pinterest

YOUR ROLE IN THIS CHAT:
- Be the strategic advisor — help with content strategy, niche decisions, growth tactics
- Explain what the system is doing and WHY (the strategic logic behind decisions)
- Give data-driven opinions on Pinterest growth, viral content, affiliate marketing
- Suggest improvements, new niches, or content angles when asked
- Keep responses crisp — 3-5 sentences max unless a detailed breakdown is asked
- Never be boring. Be energetic but grounded in strategy."""

@app.post("/api/cmo-chat")
async def cmo_chat_endpoint(req: ChatMessage):
    msg = req.message.strip()
    if not msg:
        return {"response": "Ask me anything about strategy, growth, or the system! 🧠", "action": None}

    if not _gemini_client:
        return {
            "response": "Gemini API key nahi mila — GEMINI_API_KEY secret set karo aur restart karo. 🔑",
            "action": None
        }

    sys_ctx = (
        f"Live system snapshot — "
        f"Mastermind: {'RUNNING 🟢' if state['mastermind_running'] else 'IDLE ⚪'}. "
        f"Last run: {state['mastermind_last_run'] or 'Never'}. "
        f"Account 1 strategy: {state['mastermind_a1_strategy']}. "
        f"Account 2 strategy: {state['mastermind_a2_strategy']}. "
        f"Pins posted today: {state['posted_today']}."
    )

    full_prompt = f"{CMO_SYSTEM_PROMPT}\n\n[LIVE CONTEXT]: {sys_ctx}\n\n[USER]: {msg}\n\n[CEO MASTERMIND]:"

    try:
        from google.genai import types as _gtypes
        response = await asyncio.to_thread(
            lambda: _gemini_client.models.generate_content(
                model="gemini-2.0-flash-lite",
                contents=full_prompt,
                config=_gtypes.GenerateContentConfig(
                    temperature=0.8,
                    max_output_tokens=350,
                )
            )
        )
        reply = response.text.strip() if response.text else "Strategy mode mein hoon — thodi der baad pooch! 🧠"
    except Exception as e:
        logger.error(f"CMO chat error: {e}")
        reply = "Mastermind temporarily offline. Board meeting mein hoon — 2 minute mein wapas! 😄"

    return {"response": reply, "action": None}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
