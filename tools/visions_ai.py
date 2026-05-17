import os
import io
import time
import json
import logging
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, SPREADSHEET_ID, GOOGLE_CREDS_JSON as CREDENTIALS_JSON, GEMINI_API_KEY_2

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

# Google Drive Folder IDs
DRIVE_INPUT_FOLDER_ID = "1pazvTr_I75pqCGZW-OEwr0Bs2q_8tFnu"
DRIVE_PROCESSED_FOLDER_ID = "12S9mAhs43YRBVFCzc-xhX2BhhcoRoBBg"

SCOPES = [
    "https://spreadsheets.google.com/feeds", 
    "https://www.googleapis.com/auth/drive"
]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ══════════════════════════════════════════════════════════════════════════════
# CLIENTS SETUP
# ══════════════════════════════════════════════════════════════════════════════

# Primary + Fallback Gemini clients
_primary_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
_fallback_client = genai.Client(api_key=GEMINI_API_KEY_2) if GEMINI_API_KEY_2 else None
import json as _json
_creds_dict = _json.loads(CREDENTIALS_JSON) if isinstance(CREDENTIALS_JSON, str) else CREDENTIALS_JSON
creds = Credentials.from_service_account_info(_creds_dict, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=creds)

# ══════════════════════════════════════════════════════════════════════════════
# CORE FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def append_to_sheet(data: dict):
    """Google Sheet me extracted DNA ko append karta hai."""
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(SPREADSHEET_ID).worksheet("Prompts_Master")
    
    row = [
        data.get("style_key", ""),
        data.get("account", "account_1"),
        data.get("label", ""),
        data.get("description", ""),
        data.get("t2i_base", ""),
        data.get("niche_affinity", ""),
        data.get("tags", "")
    ]
    sheet.append_row(row)
    logging.info(f"✅ Sheet Updated: {data.get('style_key')}")

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

def _get_today_processed():
    """Aaj kitni images process hui hain."""
    from datetime import date
    today = str(date.today())
    if _today_count["date"] != today:
        _today_count["date"] = today
        _today_count["count"] = 0
    return _today_count["count"]

def _increment_today():
    from datetime import date
    _today_count["date"] = str(date.today())
    _today_count["count"] += 1

def run_feeder_agent():
    """Main Drive Loop - Returns number of images processed"""
    # Daily limit check
    done_today = _get_today_processed()
    if done_today >= DAILY_IMAGE_LIMIT:
        logging.info(f"🛑 Daily limit reached ({DAILY_IMAGE_LIMIT} images). Resuming tomorrow.")
        return 0

    remaining = DAILY_IMAGE_LIMIT - done_today

    # Check Drive for images
    results = drive_service.files().list(
        q=f"'{DRIVE_INPUT_FOLDER_ID}' in parents and trashed=false",
        pageSize=remaining,
        fields="files(id, name, mimeType)"
    ).execute()
    
    items = results.get('files', [])
    images = [f for f in items if f['mimeType'].startswith('image/')][:remaining]

    if not images:
        return 0

    logging.info(f"🚀 Found {len(images)} images | Processed today: {done_today}/{DAILY_IMAGE_LIMIT}")
    
    for img in images:
        file_id = img['id']
        file_name = img['name']
        temp_path = f"/tmp/temp_{file_name}"
        
        try:
            logging.info(f"📥 Downloading: {file_name}")
            download_from_drive(file_id, temp_path)
            
            logging.info(f"🔍 Analyzing aesthetic DNA...")
            extracted_dna = analyze_image(temp_path)
            
            logging.info("📝 Pushing to Prompts_Master Sheet...")
            append_to_sheet(extracted_dna)
            
            logging.info("🗂️ Moving to Processed Folder...")
            move_file_in_drive(file_id, DRIVE_INPUT_FOLDER_ID, DRIVE_PROCESSED_FOLDER_ID)
            
            # Cleanup local temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)
            
            _increment_today()
            logging.info(f"✅ Today: {_get_today_processed()}/{DAILY_IMAGE_LIMIT} images done.")
            logging.info("⏳ Waiting 30 seconds for next scan (Rate Limit Safety)...")
            time.sleep(30)
            
        except Exception as e:
            logging.error(f"❌ Error with {file_name}: {e}")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            logging.info("⏳ Pausing for 60 seconds due to error...")
            time.sleep(60)
            
    return len(images)

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
