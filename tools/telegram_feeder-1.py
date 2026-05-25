"""
╔══════════════════════════════════════════════════════════════╗
║     TELEGRAM VISION FEEDER — Pinteresto v3                   ║
║     WEBHOOK MODE (HuggingFace compatible)                    ║
║                                                              ║
║  Flow:                                                       ║
║   Telegram → POST /api/telegram-webhook → image save        ║
║   → /tmp/tg_queue/ mein store                               ║
║   → Roz 10 images automatically process hoti hain           ║
║   → Gemini analyze → Prompts_Master sheet                   ║
╚══════════════════════════════════════════════════════════════╝

SETUP (ek baar):
1. @BotFather se bot banao → TELEGRAM_BOT_TOKEN
2. @userinfobot se TELEGRAM_CHAT_ID pata karo
3. HF Secrets mein dono daalo + APP_URL (tera HF space URL)
4. App deploy hone ke baad webhook auto-register hoga lifespan() mein
"""

import os
import time
import json
import logging
import asyncio
import requests
from datetime import date, datetime
from pathlib import Path

from google import genai
from google.genai import types
from config import GEMINI_API_KEY, GEMINI_API_KEY_2
from sheets import (
    log_to_vision_tracker,
    get_today_count_from_sheet,
    append_prompt_row,
    get_all_processed_filenames,
)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

try:
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
except ImportError:
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

DAILY_IMAGE_LIMIT = 10
QUEUE_DIR = Path("/tmp/tg_queue")
QUEUE_DIR.mkdir(parents=True, exist_ok=True)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ══════════════════════════════════════════════════════════════════════════════
# GEMINI CLIENTS
# ══════════════════════════════════════════════════════════════════════════════

_primary_client  = genai.Client(api_key=GEMINI_API_KEY)  if GEMINI_API_KEY  else None
_fallback_client = genai.Client(api_key=GEMINI_API_KEY_2) if GEMINI_API_KEY_2 else None

# ══════════════════════════════════════════════════════════════════════════════
# IN-MEMORY STATS
# ══════════════════════════════════════════════════════════════════════════════

_today_count = {"date": None, "count": 0}
_stop_flag   = {"value": False}

_tg_stats = {
    "queue_count":     0,
    "processed_today": 0,
    "daily_limit":     DAILY_IMAGE_LIMIT,
    "last_file":       "—",
    "last_time":       "—",
    "status":          "idle",
}

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_vision_stats() -> dict:
    IMAGE_EXTS = ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.gif", "*.heic", "*.heif")
    count = sum(len(list(QUEUE_DIR.glob(e))) for e in IMAGE_EXTS)
    _tg_stats["queue_count"]     = count
    _tg_stats["processed_today"] = _get_today_processed()
    return dict(_tg_stats)

def request_stop():
    _stop_flag["value"] = True
    _tg_stats["status"] = "paused"
    logging.info("🛑 Telegram Feeder: stop requested.")

def request_start():
    _stop_flag["value"] = False
    _tg_stats["status"] = "running"
    logging.info("▶️ Telegram Feeder: start requested.")

def is_stop_requested() -> bool:
    return _stop_flag["value"]

def _get_today_processed() -> int:
    today = str(date.today())
    if _today_count["date"] != today:
        _today_count["date"]  = today
        _today_count["count"] = 0
    sheet_count = get_today_count_from_sheet()
    if sheet_count > _today_count["count"]:
        _today_count["count"] = sheet_count
    return _today_count["count"]

def _increment_today():
    _today_count["date"]   = str(date.today())
    _today_count["count"] += 1

def _queue_count() -> int:
    IMAGE_EXTS = ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.gif", "*.heic", "*.heif")
    return sum(len(list(QUEUE_DIR.glob(e))) for e in IMAGE_EXTS)

# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM OUTGOING (replies)
# ══════════════════════════════════════════════════════════════════════════════

def tg_send(chat_id: str, text: str):
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        logging.warning(f"⚠️ Telegram send failed: {e}")

def tg_download_photo(file_id: str, save_path: Path) -> bool:
    try:
        r = requests.get(f"{TELEGRAM_API}/getFile",
                         params={"file_id": file_id}, timeout=10)
        r.raise_for_status()
        file_path = r.json()["result"]["file_path"]
        url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
        img_data = requests.get(url, timeout=30).content
        with open(save_path, "wb") as f:
            f.write(img_data)
        return True
    except Exception as e:
        logging.warning(f"⚠️ Photo download failed: {e}")
        return False

# ══════════════════════════════════════════════════════════════════════════════
# WEBHOOK REGISTRATION
# ══════════════════════════════════════════════════════════════════════════════

def register_webhook(app_url: str):
    """
    Telegram ko batao ki updates kahan bhejne hain.
    lifespan() mein call karo:
        from tools.telegram_feeder import register_webhook
        register_webhook(os.environ.get("APP_URL", ""))
    
    APP_URL = tera HuggingFace URL, e.g.:
        https://ksksysy540-pinteresto.hf.space
    """
    if not TELEGRAM_BOT_TOKEN or not app_url:
        logging.warning("⚠️ Webhook register skipped — TOKEN ya APP_URL missing.")
        return
    webhook_url = f"{app_url.rstrip('/')}/api/telegram-webhook"
    try:
        r = requests.post(
            f"{TELEGRAM_API}/setWebhook",
            json={"url": webhook_url, "allowed_updates": ["message"]},
            timeout=10
        )
        result = r.json()
        if result.get("ok"):
            logging.info(f"✅ Telegram Webhook registered: {webhook_url}")
        else:
            logging.warning(f"⚠️ Webhook register failed: {result}")
    except Exception as e:
        logging.warning(f"⚠️ Webhook register error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# WEBHOOK HANDLER — main.py se call hota hai
# ══════════════════════════════════════════════════════════════════════════════

async def handle_telegram_update(update: dict):
    """
    FastAPI webhook endpoint se yeh call hota hai.
    
    main.py mein add karo:
    
        @app.post("/api/telegram-webhook")
        async def telegram_webhook(request: Request):
            data = await request.json()
            await handle_telegram_update(data)
            return {"ok": True}
    """
    msg = update.get("message", {})
    if not msg:
        return

    chat_id = str(msg.get("chat", {}).get("id", ""))
    text    = msg.get("text", "")
    photos  = msg.get("photo")
    doc     = msg.get("document")

    # Security check
    if TELEGRAM_CHAT_ID and chat_id != str(TELEGRAM_CHAT_ID):
        logging.warning(f"⚠️ Unauthorized message from: {chat_id}")
        return

    # ── Commands ─────────────────────────────────────────────────────────────
    if text == "/start":
        tg_send(chat_id, (
            "🤖 <b>Vision Feeder Bot Active!</b>\n\n"
            "Images bhejo — main queue mein save kar lunga.\n"
            "Roz <b>10 images</b> automatically process hongi.\n\n"
            "/status → queue aur progress dekho"
        ))
        return

    if text in ("/status", "/queue"):
        stats  = get_vision_stats()
        tg_send(chat_id, (
            f"📊 <b>Vision Feeder Status</b>\n\n"
            f"🗂 Queue mein: <b>{stats['queue_count']} images</b>\n"
            f"✅ Aaj process hui: <b>{stats['processed_today']}/{stats['daily_limit']}</b>\n"
            f"🔄 Status: <b>{stats['status']}</b>\n"
            f"📄 Last file: <b>{stats['last_file']}</b>"
        ))
        return

    # ── Photo save ───────────────────────────────────────────────────────────
    files_to_save = []
    if photos:
        best = max(photos, key=lambda p: p.get("file_size", 0))
        files_to_save.append((best["file_id"], ".jpg"))
    elif doc and doc.get("mime_type", "").startswith("image/"):
        ext = "." + doc["mime_type"].split("/")[-1]
        files_to_save.append((doc["file_id"], ext))

    for file_id, ext in files_to_save:
        ts        = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        save_path = QUEUE_DIR / f"tg_{ts}{ext}"
        if await asyncio.to_thread(tg_download_photo, file_id, save_path):
            q_count = _queue_count()
            logging.info(f"📥 Saved: {save_path.name} | Queue: {q_count}")
            if q_count % 10 == 1 or q_count == 1:
                tg_send(chat_id,
                    f"✅ Saved! Queue mein ab <b>{q_count}</b> images hain.")
        else:
            tg_send(chat_id, "❌ Save nahi hua — dobara bhejo.")

# ══════════════════════════════════════════════════════════════════════════════
# GEMINI VISION
# ══════════════════════════════════════════════════════════════════════════════

def analyze_image(image_path: str) -> dict:
    prompt = """
    You are an Elite Visual Art Director and Reverse-Engineering Expert.
    Analyze the provided image and extract its complete aesthetic DNA into a strict JSON format.

    RULES:
    1. style_key: Create a unique snake_case name (e.g., "sunset_gaming_desk").
    2. account: If the image is Home Decor/Lifestyle/Garden, output "account_1". If it is Tech/Gaming/Desk setup, output "account_2".
    3. label: A clean, human-readable Title Case label.
    4. description: 2-3 sentences of rich, sensory description. Describe the mood, colors, and key elements.
    5. t2i_base: A highly detailed text-to-image prompt. Include specific objects, textures, and compositional technique.
       CRITICAL ENDING: Dynamically analyze the photographic style and end with 3-4 comma-separated descriptive tags.
    6. niche_affinity: Comma-separated niches (e.g., "home, cozy" or "tech, gadgets").
    7. tags: Exactly 5 CamelCase tags, comma-separated.

    Output ONLY a valid JSON object matching this exact structure.
    """
    for attempt, client in enumerate([_primary_client, _fallback_client]):
        if not client:
            continue
        label = "PRIMARY" if attempt == 0 else "FALLBACK"
        try:
            logging.info(f"🔑 Using {label} Gemini key...")
            myfile = client.files.upload(file=image_path)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[prompt, myfile],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.7
                )
            )
            client.files.delete(name=myfile.name)
            return json.loads(response.text.strip())
        except Exception as e:
            logging.warning(f"⚠️ {label} failed: {e}")
            if attempt == 1:
                raise
    raise RuntimeError("Both Gemini API keys failed.")

# ══════════════════════════════════════════════════════════════════════════════
# FEEDER AGENT
# ══════════════════════════════════════════════════════════════════════════════

def run_feeder_agent() -> int:
    if is_stop_requested():
        _tg_stats["status"] = "paused"
        return -2

    done_today = _get_today_processed()
    _tg_stats["processed_today"] = done_today

    if done_today >= DAILY_IMAGE_LIMIT:
        logging.info(f"🛑 Daily limit ({DAILY_IMAGE_LIMIT}) reached.")
        _tg_stats["status"] = "limit_reached"
        return -3

    remaining = DAILY_IMAGE_LIMIT - done_today
    _tg_stats["status"] = "scanning"

    IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif"}
    queue_files = sorted([
        f for f in QUEUE_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS
    ])
    _tg_stats["queue_count"] = len(queue_files)

    if not queue_files:
        logging.info("💤 Queue khali hai.")
        _tg_stats["status"] = "idle"
        return 0

    already_done: set = set()
    try:
        already_done = get_all_processed_filenames()
        logging.info(f"🔒 Duplicate guard: {len(already_done)} filenames.")
    except Exception as e:
        logging.warning(f"⚠️ Duplicate guard failed: {e}")

    to_process = queue_files[:remaining]
    processed  = 0
    logging.info(f"🚀 Processing {len(to_process)} | Done: {done_today}/{DAILY_IMAGE_LIMIT}")
    _tg_stats["status"] = "processing"

    for img_path in to_process:
        if is_stop_requested():
            _tg_stats["status"] = "paused"
            break

        file_name = img_path.name

        if file_name in already_done:
            logging.info(f"⏭️ Duplicate: {file_name}")
            img_path.unlink(missing_ok=True)
            _tg_stats["queue_count"] = max(0, _tg_stats["queue_count"] - 1)
            continue

        try:
            logging.info(f"🔍 Analyzing: {file_name}")
            _tg_stats["status"] = f"analyzing: {file_name[:30]}"
            extracted_dna = analyze_image(str(img_path))

            append_prompt_row(extracted_dna)
            log_to_vision_tracker(
                file_name=file_name,
                style_key=extracted_dna.get("style_key", "unknown"),
                account=extracted_dna.get("account", "unknown"),
                status="processed"
            )
            already_done.add(file_name)
            img_path.unlink(missing_ok=True)

            _increment_today()
            processed += 1

            _tg_stats["last_file"]       = file_name
            _tg_stats["last_time"]       = datetime.now().strftime("%I:%M %p")
            _tg_stats["processed_today"] = _get_today_processed()
            _tg_stats["queue_count"]     = max(0, _tg_stats["queue_count"] - 1)
            _tg_stats["status"]          = "processing"

            logging.info(f"✅ Today: {_get_today_processed()}/{DAILY_IMAGE_LIMIT}")
            time.sleep(30)

        except Exception as e:
            logging.error(f"❌ Error {file_name}: {e}")
            _tg_stats["status"] = "error"
            time.sleep(60)

    if not is_stop_requested():
        _tg_stats["status"] = "idle"
    return processed

# ══════════════════════════════════════════════════════════════════════════════
# BACKGROUND LOOPS
# ══════════════════════════════════════════════════════════════════════════════

async def telegram_feeder_loop():
    """Har ghante queue check karo, daily limit tak process karo."""
    logging.info("👁️ Telegram Feeder Loop started.")
    while True:
        try:
            result = await asyncio.to_thread(run_feeder_agent)
            if result == -3:
                logging.info("💤 Daily limit. 24h wait.")
                await asyncio.sleep(86400)
            elif result == 0:
                logging.info("💤 Queue empty. 1h wait.")
                await asyncio.sleep(3600)
            else:
                await asyncio.sleep(3600)
        except Exception as e:
            logging.error(f"❌ Feeder loop: {e}")
            await asyncio.sleep(300)

async def telegram_receiver_loop():
    """Polling disabled — webhook mode use ho raha hai HuggingFace pe."""
    logging.info("ℹ️ Webhook mode active — polling disabled.")
    while True:
        await asyncio.sleep(3600)
