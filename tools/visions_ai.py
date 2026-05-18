import os
import io
import time
import json
import logging
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, GOOGLE_CREDS_JSON as CREDENTIALS_JSON, GEMINI_API_KEY_2
from sheets import log_to_vision_tracker, get_today_count_from_sheet, append_prompt_row

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

# Google Drive Folder IDs
DRIVE_INPUT_FOLDER_ID     = "1pazvTr_I75pqCGZW-OEwr0Bs2q_8tFnu"
DRIVE_PROCESSED_FOLDER_ID = "12S9mAhs43YRBVFCzc-xhX2BhhcoRoBBg"

SCOPES = ["https://www.googleapis.com/auth/drive"]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ══════════════════════════════════════════════════════════════════════════════
# CLIENTS SETUP
# ══════════════════════════════════════════════════════════════════════════════

# Primary + Fallback Gemini clients
_primary_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
_fallback_client = genai.Client(api_key=GEMINI_API_KEY_2) if GEMINI_API_KEY_2 else None

import json as _json

creds = None
drive_service = None

try:
    _creds_dict = _json.loads(CREDENTIALS_JSON) if isinstance(CREDENTIALS_JSON, str) else CREDENTIALS_JSON
    if _creds_dict:
        creds = Credentials.from_service_account_info(_creds_dict, scopes=SCOPES)
        drive_service = build('drive', 'v3', credentials=creds)
        logging.info("✅ Google Drive service initialized.")
    else:
        logging.warning("⚠️ GOOGLE_CREDS_JSON not set — Vision Feeder will be disabled.")
except Exception as _e:
    logging.warning(f"⚠️ Google credentials init failed: {_e} — Vision Feeder will be disabled.")

# ══════════════════════════════════════════════════════════════════════════════
# CORE FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════


def analyze_image(image_path: str) -> dict:
    """Gemini Vision ka use karke strict dynamic JSON extract karta hai."""
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
    
    # Primary try, fallback on error
    for attempt, active_client in enumerate([_primary_client, _fallback_client]):
        if not active_client:
            continue
        label = "PRIMARY" if attempt == 0 else "FALLBACK"
        try:
            logging.info(f"🔑 Using {label} Gemini API key...")
            myfile = active_client.files.upload(file=image_path)
            response = active_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[prompt, myfile],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.7
                )
            )
            active_client.files.delete(name=myfile.name)
            return json.loads(response.text.strip())
        except Exception as e:
            logging.warning(f"⚠️ {label} key failed: {e}")
            if attempt == 1:
                raise
    raise RuntimeError("Both Gemini API keys failed.")

def download_from_drive(file_id: str, file_name: str):
    """Drive se temporarily local storage me image download karta hai."""
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    
    with open(file_name, 'wb') as f:
        f.write(fh.getvalue())
    return file_name

def move_file_in_drive(file_id: str, old_parent: str, new_parent: str):
    """Image ko Input folder se hata kar Processed folder me daal deta hai."""
    drive_service.files().update(
        fileId=file_id,
        addParents=new_parent,
        removeParents=old_parent,
        fields='id, parents'
    ).execute()

DAILY_IMAGE_LIMIT = 10
_today_count = {"date": None, "count": 0}

# ── Stop / Start Control Flag ──────────────────────────────────────────────
_stop_flag = {"value": False}

def request_stop():
    """Dashboard se stop signal bhejo."""
    _stop_flag["value"] = True
    _vision_stats["status"] = "paused"
    logging.info("🛑 Vision Feeder: stop requested.")

def request_start():
    """Dashboard se start signal bhejo."""
    _stop_flag["value"] = False
    _vision_stats["status"] = "running"
    logging.info("▶️ Vision Feeder: start requested.")

def is_stop_requested() -> bool:
    return _stop_flag["value"]

# ── Real-Time Stats ────────────────────────────────────────────────────────
_vision_stats = {
    "queue_count":      0,
    "processed_today":  0,
    "daily_limit":      DAILY_IMAGE_LIMIT,
    "last_file":        "—",
    "last_time":        "—",
    "status":           "idle",
}

def get_vision_stats() -> dict:
    """Dashboard ke liye live stats return karo."""
    _vision_stats["processed_today"] = _get_today_processed()
    _vision_stats["daily_limit"]     = DAILY_IMAGE_LIMIT
    return dict(_vision_stats)

# ── Internal Helpers ───────────────────────────────────────────────────────
def _get_today_processed():
    """
    Aaj kitni images process hui hain.
    Priority: Vision_Tracker sheet (sheets/ package, restart-safe) → in-memory count.
    """
    from datetime import date
    today = str(date.today())
    if _today_count["date"] != today:
        _today_count["date"] = today
        _today_count["count"] = 0
    if creds is not None:
        sheet_count = get_today_count_from_sheet()
        if sheet_count > _today_count["count"]:
            _today_count["count"] = sheet_count
    return _today_count["count"]

def _increment_today():
    from datetime import date
    _today_count["date"] = str(date.today())
    _today_count["count"] += 1

def run_feeder_agent():
    """Main Drive Loop - Returns number of images processed.
    Returns: int processed, or -1 on quota hit, or -2 if stop requested."""

    if is_stop_requested():
        _vision_stats["status"] = "paused"
        return -2

    if drive_service is None:
        logging.warning("⚠️ Vision Feeder disabled — Google credentials not configured.")
        _vision_stats["status"] = "disabled"
        return 0

    # Daily limit check
    done_today = _get_today_processed()
    _vision_stats["processed_today"] = done_today
    if done_today >= DAILY_IMAGE_LIMIT:
        logging.info(f"🛑 Daily limit reached ({DAILY_IMAGE_LIMIT} images). Sleeping 24 hours.")
        _vision_stats["status"] = "limit_reached"
        return -3  # Caller must sleep 24 hours

    remaining = DAILY_IMAGE_LIMIT - done_today
    _vision_stats["status"] = "scanning"

    # Check Drive for images
    try:
        results = drive_service.files().list(
            q=f"'{DRIVE_INPUT_FOLDER_ID}' in parents and trashed=false",
            pageSize=remaining + 20,
            fields="files(id, name, mimeType)"
        ).execute()
    except Exception as e:
        logging.error(f"❌ Drive list error: {e}")
        _vision_stats["status"] = "error"
        return 0

    items = results.get('files', [])
    images = [f for f in items if f['mimeType'].startswith('image/')]

    # Update queue count (total images in Drive, not capped)
    _vision_stats["queue_count"] = len(images)
    images = images[:remaining]

    if not images:
        _vision_stats["status"] = "idle"
        return 0

    logging.info(f"🚀 Found {len(images)} images | Processed today: {done_today}/{DAILY_IMAGE_LIMIT}")
    _vision_stats["status"] = "processing"

    processed_count = 0
    for img in images:
        # Check stop between each image
        if is_stop_requested():
            logging.info("🛑 Vision Feeder: stop flag detected mid-loop. Halting.")
            _vision_stats["status"] = "paused"
            break

        file_id   = img['id']
        file_name = img['name']
        temp_path = f"/tmp/temp_{file_name}"

        try:
            logging.info(f"📥 Downloading: {file_name}")
            _vision_stats["status"] = f"downloading: {file_name[:30]}"
            download_from_drive(file_id, temp_path)

            logging.info(f"🔍 Analyzing aesthetic DNA...")
            _vision_stats["status"] = f"analyzing: {file_name[:30]}"
            extracted_dna = analyze_image(temp_path)

            logging.info("📝 Pushing to Prompts_Master Sheet...")
            append_prompt_row(extracted_dna)

            logging.info("📋 Logging to Vision_Tracker Sheet...")
            log_to_vision_tracker(
                file_name = file_name,
                style_key = extracted_dna.get("style_key", "unknown"),
                account   = extracted_dna.get("account", "unknown"),
                status    = "processed"
            )

            logging.info("🗂️ Moving to Processed Folder...")
            move_file_in_drive(file_id, DRIVE_INPUT_FOLDER_ID, DRIVE_PROCESSED_FOLDER_ID)

            if os.path.exists(temp_path):
                os.remove(temp_path)

            _increment_today()
            processed_count += 1

            # Update stats after each image
            from datetime import datetime
            _vision_stats["last_file"]       = file_name
            _vision_stats["last_time"]       = datetime.now().strftime("%I:%M %p")
            _vision_stats["processed_today"] = _get_today_processed()
            _vision_stats["queue_count"]     = max(0, _vision_stats["queue_count"] - 1)
            _vision_stats["status"]          = "processing"

            logging.info(f"✅ Today: {_get_today_processed()}/{DAILY_IMAGE_LIMIT} images done.")
            logging.info("⏳ Waiting 30 seconds for next scan (Rate Limit Safety)...")
            time.sleep(30)

        except Exception as e:
            logging.error(f"❌ Error with {file_name}: {e}")
            _vision_stats["status"] = "error"
            if os.path.exists(temp_path):
                os.remove(temp_path)
            logging.info("⏳ Pausing for 60 seconds due to error...")
            time.sleep(60)

    if not is_stop_requested():
        _vision_stats["status"] = "idle" if processed_count == 0 else "idle"

    return processed_count

# ══════════════════════════════════════════════════════════════════════════════
# AUTO-PILOT TRIGGER
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.info("🤖 Vision Feeder Agent Started in AUTO-PILOT mode...")
    logging.info("🛑 To stop the script anytime, press CTRL + C")
    try:
        while True:
            processed_count = run_feeder_agent()
            if processed_count == 0:
                logging.info("💤 Drive is empty. Sleeping for 5 minutes before checking again...")
                time.sleep(300)
    except KeyboardInterrupt:
        logging.info("\n🛑 Script manually stopped by user (CTRL + C). System Offline.")
