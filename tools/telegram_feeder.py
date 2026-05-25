"""
╔══════════════════════════════════════════════════════════════╗
║         TELEGRAM VISION FEEDER — Pinteresto v3               ║
║  Google Drive ko replace karta hai Telegram bot se           ║
║                                                              ║
║  Flow:                                                       ║
║   Tu bot ko images bhejta hai (100 ek saath bhi)            ║
║   → Bot /tmp/tg_queue/ mein save karta hai                   ║
║   → Roz 10 images automatically process hoti hain           ║
║   → Gemini analyze karta hai → Prompts_Master sheet          ║
║   → Vision_Tracker mein log hota hai                        ║
╚══════════════════════════════════════════════════════════════╝

SETUP:
1. @BotFather se naya bot banao → TELEGRAM_BOT_TOKEN milega
2. Apna TELEGRAM_CHAT_ID pata karo (@userinfobot se)
3. Dono secrets config.py / Replit Secrets mein daalo
4. main.py mein vision_feeder_loop() ko telegram_feeder_loop() se replace karo

COMMANDS:
  /status  → aaj kitni process hui, queue mein kitni hain
  /start   → welcome message
  Images bhejo → automatically queue mein save
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
QUEUE_DIR = Path("/tmp/tg_queue")          # Pending images yahan save hongi
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
    """Dashboard ke liye stats — visions_ai.py ke get_vision_stats() jaisa interface."""
    _tg_stats["queue_count"]     = len(list(QUEUE_DIR.glob("*.jpg"))) + \
                                   len(list(QUEUE_DIR.glob("*.png"))) + \
                                   len(list(QUEUE_DIR.glob("*.webp")))
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
    return sum(1 for _ in QUEUE_DIR.iterdir() if _.is_file())

# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM API HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _tg_send(chat_id: str, text: str):
    """Telegram mein message bhejo."""
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        logging.warning(f"⚠️ Telegram send failed: {e}")

def _tg_get_updates(offset: int = 0) -> list:
    """Naye messages fetch karo."""
    try:
        r = requests.get(f"{TELEGRAM_API}/getUpdates", params={
            "offset": offset,
            "timeout": 30,
            "allowed_updates": ["message"]
        }, timeout=35)
        return r.json().get("result", [])
    except Exception as e:
        logging.warning(f"⚠️ Telegram getUpdates failed: {e}")
        return []

def _tg_download_photo(file_id: str, save_path: Path) -> bool:
    """Telegram se photo download karke queue mein save karo."""
    try:
        # Step 1: file path get karo
        r = requests.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id}, timeout=10)
        file_path = r.json()["result"]["file_path"]

        # Step 2: download karo
        url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
        img_data = requests.get(url, timeout=30).content

        # Step 3: save karo
        with open(save_path, "wb") as f:
            f.write(img_data)
        return True
    except Exception as e:
        logging.warning(f"⚠️ Photo download failed: {e}")
        return False

# ══════════════════════════════════════════════════════════════════════════════
# GEMINI VISION ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def analyze_image(image_path: str) -> dict:
    """Gemini Vision se aesthetic DNA extract karo — visions_ai.py jaisa same prompt."""
    prompt = """
    You are an Elite Visual Art Director and Reverse-Engineering Expert.
    Analyze the provided image and extract its complete aesthetic DNA into a strict JSON format.
    
    RULES:
    1. style_key: Create a unique snake_case name (e.g., "sunset_gaming_desk").
    2. account: If the image is Home Decor/Lifestyle/Garden, output "account_1". If it is Tech/Gaming/Desk setup, output "account_2".
    3. label: A clean, human-readable Title Case label.
    4. description: 2-3 sentences of rich, sensory description. Describe the mood, colors, and key elements.
    5. t2i_base: A highly detailed text-to-image prompt. Include specific objects, textures, and compositional technique. 
       CRITICAL ENDING: Do NOT use a hardcoded ending. You must dynamically analyze the exact photographic style, lighting finish, or rendering aesthetic of the specific image and end the prompt with 3-4 comma-separated descriptive tags. 
       (Examples: "warm twilight lighting, cozy amber glow, soft indoor lifestyle photography" OR "hyper-detailed digital art, vivid saturated colors, majestic sunset lighting, unreal engine 5 style".)
    6. niche_affinity: Comma-separated niches (e.g., "home, cozy" or "tech, gadgets").
    7. tags: Exactly 5 CamelCase tags, comma-separated (e.g., "AestheticRoom, CozyVibes").
    
    Output ONLY a valid JSON object matching this exact structure.
    """

    for attempt, client in enumerate([_primary_client, _fallback_client]):
        if not client:
            continue
        label = "PRIMARY" if attempt == 0 else "FALLBACK"
        try:
            logging.info(f"🔑 Using {label} Gemini API key...")
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
            logging.warning(f"⚠️ {label} key failed: {e}")
            if attempt == 1:
                raise
    raise RuntimeError("Both Gemini API keys failed.")

# ══════════════════════════════════════════════════════════════════════════════
# CORE: IMAGE RECEIVER LOOP (Telegram se images queue mein save karo)
# ══════════════════════════════════════════════════════════════════════════════

async def telegram_receiver_loop():
    """
    Background loop — Telegram bot ke messages sunata hai.
    Images automatically queue mein save hoti hain.
    Commands handle karta hai (/status, /start).
    
    main.py mein asyncio.create_task(telegram_receiver_loop()) se start karo.
    """
    if not TELEGRAM_BOT_TOKEN:
        logging.warning("⚠️ TELEGRAM_BOT_TOKEN not set — Telegram receiver disabled.")
        return

    logging.info("🤖 Telegram Receiver Loop started — bot sun raha hai...")
    offset = 0

    while True:
        try:
            updates = _tg_get_updates(offset)

            for update in updates:
                offset = update["update_id"] + 1
                msg    = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))

                # Security: sirf authorized chat se messages accept karo
                if TELEGRAM_CHAT_ID and chat_id != str(TELEGRAM_CHAT_ID):
                    logging.warning(f"⚠️ Unauthorized message from chat_id: {chat_id}")
                    continue

                # ── Commands ───────────────────────────────────────────────
                text = msg.get("text", "")
                if text == "/start":
                    _tg_send(chat_id, (
                        "🤖 <b>Vision Feeder Bot Active!</b>\n\n"
                        "Images bhejo — main queue mein save kar lunga.\n"
                        "Roz <b>10 images</b> automatically process hongi.\n\n"
                        "/status → queue aur progress dekho"
                    ))
                    continue

                if text == "/status":
                    stats    = get_vision_stats()
                    q        = stats["queue_count"]
                    done     = stats["processed_today"]
                    limit    = stats["daily_limit"]
                    last     = stats["last_file"]
                    status   = stats["status"]
                    _tg_send(chat_id, (
                        f"📊 <b>Vision Feeder Status</b>\n\n"
                        f"🗂 Queue mein: <b>{q} images</b>\n"
                        f"✅ Aaj process hui: <b>{done}/{limit}</b>\n"
                        f"🔄 Status: <b>{status}</b>\n"
                        f"📄 Last file: <b>{last}</b>"
                    ))
                    continue

                # ── Photo messages ─────────────────────────────────────────
                photos = msg.get("photo")
                doc    = msg.get("document")

                files_to_save = []

                if photos:
                    # Sabse badi photo lo (best quality)
                    best = max(photos, key=lambda p: p.get("file_size", 0))
                    files_to_save.append((best["file_id"], ".jpg"))

                elif doc and doc.get("mime_type", "").startswith("image/"):
                    ext = "." + doc["mime_type"].split("/")[-1]
                    files_to_save.append((doc["file_id"], ext))

                for file_id, ext in files_to_save:
                    # Unique filename banao
                    ts        = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    save_path = QUEUE_DIR / f"tg_{ts}{ext}"

                    if _tg_download_photo(file_id, save_path):
                        q_count = _queue_count()
                        logging.info(f"📥 Saved to queue: {save_path.name} | Queue: {q_count}")
                        # Har 10 images pe ek confirmation bhejo (spam se bachao)
                        if q_count % 10 == 1:
                            _tg_send(chat_id, f"✅ Queue mein save! Abhi <b>{q_count}</b> images pending hain.")
                    else:
                        _tg_send(chat_id, "❌ Image save nahi hui, dobara bhejo.")

        except Exception as e:
            logging.error(f"❌ Telegram receiver error: {e}")

        await asyncio.sleep(2)  # 2 second polling

# ══════════════════════════════════════════════════════════════════════════════
# CORE: FEEDER AGENT (Queue se images process karo)
# ══════════════════════════════════════════════════════════════════════════════

def run_feeder_agent() -> int:
    """
    Main processing loop — visions_ai.py ke run_feeder_agent() ka drop-in replacement.
    Queue se images uthata hai, Gemini se analyze karta hai, sheets mein push karta hai.
    
    Returns:
        int  → processed count
        -2   → stop requested
        -3   → daily limit reached
    """
    if is_stop_requested():
        _tg_stats["status"] = "paused"
        return -2

    # Daily limit check
    done_today = _get_today_processed()
    _tg_stats["processed_today"] = done_today

    if done_today >= DAILY_IMAGE_LIMIT:
        logging.info(f"🛑 Daily limit reached ({DAILY_IMAGE_LIMIT}). Kal phir chalega.")
        _tg_stats["status"] = "limit_reached"
        return -3

    remaining = DAILY_IMAGE_LIMIT - done_today
    _tg_stats["status"] = "scanning"

    # Queue se images list karo
    IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif"}
    queue_files = sorted([
        f for f in QUEUE_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS
    ])

    _tg_stats["queue_count"] = len(queue_files)

    if not queue_files:
        logging.info("💤 Queue khali hai. Koi image nahi mili.")
        _tg_stats["status"] = "idle"
        return 0

    # Already processed filenames (duplicate guard)
    already_done: set = set()
    try:
        already_done = get_all_processed_filenames()
        logging.info(f"🔒 Duplicate guard: {len(already_done)} filenames loaded.")
    except Exception as e:
        logging.warning(f"⚠️ Duplicate guard failed: {e}")

    to_process  = queue_files[:remaining]
    processed   = 0
    logging.info(f"🚀 Processing {len(to_process)} images | Done today: {done_today}/{DAILY_IMAGE_LIMIT}")
    _tg_stats["status"] = "processing"

    for img_path in to_process:
        if is_stop_requested():
            logging.info("🛑 Stop flag detected mid-loop.")
            _tg_stats["status"] = "paused"
            break

        file_name = img_path.name

        # Duplicate check
        if file_name in already_done:
            logging.info(f"⏭️ Already processed, deleting from queue: {file_name}")
            img_path.unlink(missing_ok=True)
            _tg_stats["queue_count"] = max(0, _tg_stats["queue_count"] - 1)
            continue

        try:
            logging.info(f"🔍 Analyzing: {file_name}")
            _tg_stats["status"] = f"analyzing: {file_name[:30]}"

            extracted_dna = analyze_image(str(img_path))

            logging.info("📝 Pushing to Prompts_Master Sheet...")
            append_prompt_row(extracted_dna)

            logging.info("📋 Logging to Vision_Tracker Sheet...")
            log_to_vision_tracker(
                file_name = file_name,
                style_key = extracted_dna.get("style_key", "unknown"),
                account   = extracted_dna.get("account",   "unknown"),
                status    = "processed"
            )
            already_done.add(file_name)

            # Queue se delete karo (processed folder ki zaroorat nahi)
            img_path.unlink(missing_ok=True)
            logging.info(f"🗑️ Deleted from queue: {file_name}")

            _increment_today()
            processed += 1

            _tg_stats["last_file"]       = file_name
            _tg_stats["last_time"]       = datetime.now().strftime("%I:%M %p")
            _tg_stats["processed_today"] = _get_today_processed()
            _tg_stats["queue_count"]     = max(0, _tg_stats["queue_count"] - 1)
            _tg_stats["status"]          = "processing"

            logging.info(f"✅ Today: {_get_today_processed()}/{DAILY_IMAGE_LIMIT} done.")
            logging.info("⏳ 30 second wait (rate limit safety)...")
            time.sleep(30)

        except Exception as e:
            logging.error(f"❌ Error with {file_name}: {e}")
            _tg_stats["status"] = "error"
            time.sleep(60)

    if not is_stop_requested():
        _tg_stats["status"] = "idle"

    return processed

# ══════════════════════════════════════════════════════════════════════════════
# BACKGROUND LOOP (main.py mein use karo)
# ══════════════════════════════════════════════════════════════════════════════

async def telegram_feeder_loop():
    """
    main.py mein vision_feeder_loop() ki jagah yeh use karo:

        asyncio.create_task(telegram_feeder_loop())

    Har ghante mein queue check karta hai aur daily limit tak process karta hai.
    """
    logging.info("👁️ Telegram Feeder Loop started.")
    while True:
        try:
            result = run_feeder_agent()
            if result == -3:
                # Daily limit hit — kal subah tak wait karo
                logging.info("💤 Daily limit reached. 24 hours wait.")
                await asyncio.sleep(86400)
            elif result == 0:
                # Queue khali — 1 ghante baad check karo
                logging.info("💤 Queue empty. Next check in 1 hour.")
                await asyncio.sleep(3600)
            else:
                # Kuch process hua — 1 ghante baad phir check
                await asyncio.sleep(3600)
        except Exception as e:
            logging.error(f"❌ Feeder loop error: {e}")
            await asyncio.sleep(300)
            
