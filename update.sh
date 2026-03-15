#!/bin/bash
cd ~/pinteresto

echo "📦 Updating requirements.txt..."
cat > requirements.txt << 'EOF'
groq
gspread
google-auth
httpx
Pillow
apscheduler
python-dotenv
fastapi
uvicorn
EOF

echo "⚙️ Updating config.py..."
cat > config.py << 'EOF'
import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = "llama-3.3-70b-versatile"

GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SHEET_NAME = "Sheet1"

MAKE_WEBHOOK_URL = os.getenv("MAKE_WEBHOOK_URL")
PINTEREST_BOARD = os.getenv("PINTEREST_BOARD", "COOL OUTFITS")

DIGISTORE_API_KEY = os.getenv("DIGISTORE_API_KEY")

MAX_PRODUCTS_TO_FETCH = 50
MAX_PRODUCTS_TO_APPROVE = 20
DAILY_POST_LIMIT = 2
LOW_STOCK_THRESHOLD = 5

ALLOWED_CATEGORIES = [
    "health", "fitness", "weight loss", "diet",
    "beauty", "spirituality", "self help",
    "make money", "internet marketing"
]
BLOCKED_CATEGORIES = ["adult", "gambling", "casino", "dating"]
EOF

echo "🔧 Creating tools/digistore.py..."
cat > tools/digistore.py << 'EOF'
import httpx
import logging
from config import MAX_PRODUCTS_TO_FETCH, ALLOWED_CATEGORIES, BLOCKED_CATEGORIES

logger = logging.getLogger(__name__)

async def fetch_digistore_products(api_key: str) -> list:
    url = "https://www.digistore24.com/api/call/listProductsForAffiliate/format/json"
    params = {"api_key": api_key, "language": "en", "currency": "USD"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, params=params)
        data = response.json()
        raw = data.get("data", {}).get("products", [])
        logger.info(f"📦 Raw products from Digistore: {len(raw)}")
        normalized = []
        for p in raw:
            category = p.get("category", "").lower()
            if any(b in category for b in BLOCKED_CATEGORIES):
                continue
            if not any(a in category for a in ALLOWED_CATEGORIES):
                continue
            normalized.append({
                "product_name": p.get("name", ""),
                "gravity": p.get("units_sold", 0),
                "category": p.get("category", ""),
                "affiliate_link": p.get("affiliate_url", ""),
                "image_url": p.get("picture", "")
            })
            if len(normalized) >= MAX_PRODUCTS_TO_FETCH:
                break
        logger.info(f"✅ After category filter: {len(normalized)} products")
        return normalized
    except Exception as e:
        logger.error(f"❌ Digistore error: {e}")
        return []
EOF

echo "🤖 Updating tools/groq_ai.py..."
cat > tools/groq_ai.py << 'EOF'
import json
import logging
from groq import Groq
from config import GROQ_API_KEY, GROQ_MODEL

logger = logging.getLogger(__name__)
client = Groq(api_key=GROQ_API_KEY)

def _chat(prompt: str, temperature: float = 0.1) -> str:
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature
    )
    return response.choices[0].message.content

def filter_product(product: dict) -> bool:
    prompt = f"""You are an affiliate marketing expert. Analyze this product.
Product: {json.dumps(product)}
APPROVE if: legitimate digital product, health/fitness/self-help/make money niche, has real image URL
REJECT if: scammy claims, adult/gambling content, no image, 0 sales
Respond ONLY with JSON: {{"approve": true, "reason": "brief reason"}}"""
    try:
        raw = _chat(prompt, temperature=0.1).strip()
        if "```" in raw:
            raw = raw.split("```")[1].replace("json", "").strip()
        result = json.loads(raw)
        status = "✅" if result["approve"] else "❌"
        logger.info(f"{status} {product.get('product_name')}: {result.get('reason')}")
        return result["approve"]
    except Exception as e:
        logger.error(f"Filter error: {e}")
        return False

def generate_pin_copy(product: dict) -> dict:
    prompt = f"""You are a Pinterest marketing expert. Create viral pin content.
Product: {json.dumps(product)}
Rules:
- Title: Max 100 chars, curiosity hook
- Description: Max 500 chars, problem to solution, soft CTA
- Tags: 5 trending hashtags (no spaces, no #)
Respond ONLY with JSON: {{"title": "...", "description": "...", "tags": ["tag1","tag2","tag3","tag4","tag5"]}}"""
    try:
        raw = _chat(prompt, temperature=0.7).strip()
        if "```" in raw:
            raw = raw.split("```")[1].replace("json", "").strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Copy error: {e}")
        return {
            "title": product.get("product_name", "Check this"),
            "description": "Amazing product worth checking!",
            "tags": ["health", "wellness", "affiliate", "tips", "lifestyle"]
        }
EOF

echo "🔄 Updating phases/phase1_filter.py..."
cat > phases/phase1_filter.py << 'EOF'
import os
import logging
from tools.groq_ai import filter_product
from tools.google_drive import save_products
from tools.digistore import fetch_digistore_products
from config import MAX_PRODUCTS_TO_APPROVE

logger = logging.getLogger(__name__)

async def run_filter_bot():
    logger.info("🔍 Phase 1: Filter Bot started")
    api_key = os.getenv("DIGISTORE_API_KEY")
    if not api_key:
        logger.error("❌ DIGISTORE_API_KEY missing!")
        return []
    products = await fetch_digistore_products(api_key)
    if not products:
        logger.error("❌ No products fetched!")
        return []
    approved = []
    for product in products:
        if len(approved) >= MAX_PRODUCTS_TO_APPROVE:
            logger.info(f"✅ Max approve limit reached ({MAX_PRODUCTS_TO_APPROVE})")
            break
        if filter_product(product):
            approved.append(product)
    logger.info(f"📊 {len(approved)} approved / {len(products)} fetched")
    if approved:
        save_products(approved)
    return approved
EOF

echo "📊 Updating tools/google_drive.py..."
cat > tools/google_drive.py << 'EOF'
import gspread
import json
import logging
from google.oauth2.service_account import Credentials
from config import GOOGLE_CREDS_JSON, SPREADSHEET_ID, SHEET_NAME

logger = logging.getLogger(__name__)

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

def _get_sheet():
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

def get_pending_products(limit: int = 2) -> list:
    sheet = _get_sheet()
    records = sheet.get_all_records()
    pending = [r for r in records if r.get("Status") == "PENDING"]
    logger.info(f"📋 Found {len(pending)} pending products")
    return pending[:limit]

def mark_as_posted(product_name: str) -> bool:
    sheet = _get_sheet()
    records = sheet.get_all_records()
    headers = sheet.row_values(1)
    status_col = headers.index("Status") + 1
    for i, record in enumerate(records, start=2):
        if record.get("product_name") == product_name:
            sheet.update_cell(i, status_col, "POSTED")
            logger.info(f"✅ Marked POSTED: {product_name}")
            return True
    return False

def save_products(products: list) -> None:
    sheet = _get_sheet()
    for p in products:
        sheet.append_row([
            p.get("product_name"),
            p.get("gravity"),
            p.get("category"),
            p.get("affiliate_link"),
            p.get("image_url"),
            "PENDING"
        ])
    logger.info(f"💾 Saved {len(products)} products to sheet")

def count_pending() -> int:
    sheet = _get_sheet()
    records = sheet.get_all_records()
    return sum(1 for r in records if r.get("Status") == "PENDING")

def get_all_products() -> list:
    sheet = _get_sheet()
    return sheet.get_all_records()
EOF

echo "🌐 Creating static/index.html dashboard..."
mkdir -p static
cat > static/index.html << 'HTMLEOF'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pinteresto Control Panel</title>
<link href="https://fonts.googleapis.com/css2?family=Syne+Mono&family=Syne:wght@400;600;800&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #080a0c; --surface: #0e1114; --border: #1e2329;
    --accent: #f97316; --accent2: #fb923c;
    --green: #22c55e; --red: #ef4444; --yellow: #eab308;
    --text: #e2e8f0; --muted: #475569; --card: #0d1117;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: var(--bg); color: var(--text); font-family: 'Syne', sans-serif; min-height: 100vh; }
  body::before {
    content: ''; position: fixed; inset: 0; pointer-events: none; z-index: 0;
    background: radial-gradient(ellipse 80% 50% at 50% -20%, rgba(249,115,22,0.08) 0%, transparent 60%),
      repeating-linear-gradient(0deg, transparent, transparent 40px, rgba(249,115,22,0.02) 40px, rgba(249,115,22,0.02) 41px),
      repeating-linear-gradient(90deg, transparent, transparent 40px, rgba(249,115,22,0.02) 40px, rgba(249,115,22,0.02) 41px);
  }
  .wrap { position: relative; z-index: 1; max-width: 1400px; margin: 0 auto; padding: 24px; }
  header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 20px 28px; background: var(--card); border: 1px solid var(--border);
    border-radius: 12px; margin-bottom: 24px; position: relative; overflow: hidden;
  }
  header::after { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: linear-gradient(90deg, transparent, var(--accent), transparent); }
  .logo { display: flex; align-items: center; gap: 14px; }
  .logo-icon { width: 44px; height: 44px; background: linear-gradient(135deg, var(--accent), #c2410c); border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 22px; }
  .logo-text h1 { font-size: 20px; font-weight: 800; }
  .logo-text span { font-size: 12px; color: var(--muted); font-family: 'Syne Mono', monospace; }
  .header-right { display: flex; align-items: center; gap: 12px; }
  .status-pill { display: flex; align-items: center; gap: 8px; padding: 8px 16px; border-radius: 100px; font-size: 13px; font-weight: 600; border: 1px solid; }
  .status-pill.running { background: rgba(34,197,94,0.1); border-color: rgba(34,197,94,0.3); color: var(--green); }
  .status-pill.stopped { background: rgba(239,68,68,0.1); border-color: rgba(239,68,68,0.3); color: var(--red); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
  .time-badge { font-family: 'Syne Mono', monospace; font-size: 12px; color: var(--muted); padding: 8px 14px; border: 1px solid var(--border); border-radius: 8px; }
  .stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }
  .stat-card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px 24px; position: relative; overflow: hidden; transition: border-color 0.2s, transform 0.2s; }
  .stat-card:hover { border-color: var(--accent); transform: translateY(-2px); }
  .stat-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; border-radius: 12px 12px 0 0; }
  .stat-card.orange::before { background: var(--accent); }
  .stat-card.green::before { background: var(--green); }
  .stat-card.yellow::before { background: var(--yellow); }
  .stat-card.red::before { background: var(--red); }
  .stat-label { font-size: 11px; color: var(--muted); letter-spacing: 2px; text-transform: uppercase; margin-bottom: 10px; }
  .stat-value { font-size: 36px; font-weight: 800; line-height: 1; margin-bottom: 6px; }
  .stat-card.orange .stat-value { color: var(--accent); }
  .stat-card.green .stat-value { color: var(--green); }
  .stat-card.yellow .stat-value { color: var(--yellow); }
  .stat-card.red .stat-value { color: var(--red); }
  .stat-sub { font-size: 12px; color: var(--muted); font-family: 'Syne Mono', monospace; }
  .main-grid { display: grid; grid-template-columns: 1fr 380px; gap: 20px; margin-bottom: 24px; }
  .panel { background: var(--card); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
  .panel-header { padding: 16px 20px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }
  .panel-title { font-size: 13px; font-weight: 700; letter-spacing: 2px; text-transform: uppercase; color: var(--accent); }
  .panel-body { padding: 20px; }
  .phase-list { display: flex; flex-direction: column; gap: 12px; }
  .phase-item { display: flex; align-items: center; justify-content: space-between; padding: 16px 18px; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; transition: border-color 0.2s; }
  .phase-item:hover { border-color: var(--accent); }
  .phase-info { display: flex; align-items: center; gap: 14px; }
  .phase-num { width: 36px; height: 36px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 14px; background: rgba(249,115,22,0.15); color: var(--accent); border: 1px solid rgba(249,115,22,0.3); }
  .phase-name { font-size: 14px; font-weight: 600; margin-bottom: 2px; }
  .phase-desc { font-size: 11px; color: var(--muted); }
  .btn { padding: 8px 18px; border-radius: 8px; font-size: 12px; font-weight: 700; cursor: pointer; border: none; font-family: 'Syne', sans-serif; transition: all 0.2s; display: flex; align-items: center; gap: 6px; }
  .btn-primary { background: var(--accent); color: #000; }
  .btn-primary:hover { background: var(--accent2); transform: scale(1.03); }
  .btn-primary:disabled { background: var(--muted); cursor: not-allowed; transform: none; }
  .btn-ghost { background: transparent; color: var(--muted); border: 1px solid var(--border); }
  .btn-ghost:hover { border-color: var(--accent); color: var(--accent); }
  .btn-danger { background: rgba(239,68,68,0.15); color: var(--red); border: 1px solid rgba(239,68,68,0.3); }
  .btn-danger:hover { background: rgba(239,68,68,0.25); }
  .log-container { background: #060809; border-radius: 8px; padding: 14px; height: 300px; overflow-y: auto; font-family: 'Syne Mono', monospace; font-size: 11px; line-height: 1.8; border: 1px solid var(--border); }
  .log-container::-webkit-scrollbar { width: 4px; }
  .log-container::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
  .log-line { display: flex; gap: 12px; }
  .log-time { color: var(--muted); min-width: 80px; }
  .log-level-info { color: #60a5fa; }
  .log-level-success { color: var(--green); }
  .log-level-error { color: var(--red); }
  .log-level-warn { color: var(--yellow); }
  .products-panel { grid-column: 1 / -1; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; font-size: 10px; letter-spacing: 2px; text-transform: uppercase; color: var(--muted); padding: 12px 16px; border-bottom: 1px solid var(--border); }
  td { padding: 12px 16px; font-size: 13px; border-bottom: 1px solid rgba(30,35,41,0.5); }
  tr:hover td { background: rgba(249,115,22,0.03); }
  .badge { display: inline-flex; align-items: center; gap: 5px; padding: 3px 10px; border-radius: 100px; font-size: 11px; font-weight: 700; font-family: 'Syne Mono', monospace; }
  .badge-pending { background: rgba(234,179,8,0.15); color: var(--yellow); border: 1px solid rgba(234,179,8,0.3); }
  .badge-posted { background: rgba(34,197,94,0.15); color: var(--green); border: 1px solid rgba(34,197,94,0.3); }
  .badge-dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
  .toast-wrap { position: fixed; bottom: 24px; right: 24px; display: flex; flex-direction: column; gap: 10px; z-index: 999; }
  .toast { padding: 12px 20px; background: var(--card); border: 1px solid var(--border); border-radius: 10px; font-size: 13px; display: flex; align-items: center; gap: 10px; animation: slideIn 0.3s ease; min-width: 280px; }
  .toast.success { border-color: rgba(34,197,94,0.4); }
  .toast.error { border-color: rgba(239,68,68,0.4); }
  @keyframes slideIn { from{transform:translateX(100px);opacity:0} to{transform:translateX(0);opacity:1} }
  .spinner { width: 14px; height: 14px; border: 2px solid rgba(0,0,0,0.3); border-top-color: #000; border-radius: 50%; animation: spin 0.8s linear infinite; display: none; }
  @keyframes spin { to{transform:rotate(360deg)} }
  .btn.loading .spinner { display: block; }
  .btn.loading .btn-text { opacity: 0.7; }
  @media(max-width:900px){ .stats-grid{grid-template-columns:repeat(2,1fr)} .main-grid{grid-template-columns:1fr} }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo">
      <div class="logo-icon">📌</div>
      <div class="logo-text">
        <h1>Pinteresto Control Panel</h1>
        <span>Digistore24 Affiliate Bot</span>
      </div>
    </div>
    <div class="header-right">
      <div class="time-badge" id="clock">--:--:--</div>
      <div class="status-pill stopped" id="botStatus">
        <div class="dot"></div>
        <span id="statusText">Checking...</span>
      </div>
    </div>
  </header>

  <div class="stats-grid">
    <div class="stat-card orange">
      <div class="stat-label">Pending Products</div>
      <div class="stat-value" id="statPending">--</div>
      <div class="stat-sub">In Google Sheets</div>
    </div>
    <div class="stat-card green">
      <div class="stat-label">Posted Today</div>
      <div class="stat-value" id="statPosted">--</div>
      <div class="stat-sub">Pins on Pinterest</div>
    </div>
    <div class="stat-card yellow">
      <div class="stat-label">Total Products</div>
      <div class="stat-value" id="statTotal">--</div>
      <div class="stat-sub">In Sheet</div>
    </div>
    <div class="stat-card red">
      <div class="stat-label">Last Run</div>
      <div class="stat-value" style="font-size:18px;padding-top:6px" id="statLastRun">--</div>
      <div class="stat-sub">APScheduler</div>
    </div>
  </div>

  <div class="main-grid">
    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">⚙ Phase Controls</span>
        <button class="btn btn-ghost" onclick="refreshAll()">↻ Refresh</button>
      </div>
      <div class="panel-body">
        <div class="phase-list">
          <div class="phase-item">
            <div class="phase-info">
              <div class="phase-num">1</div>
              <div>
                <div class="phase-name">Filter Bot</div>
                <div class="phase-desc">Digistore → AI Filter → Google Sheets</div>
              </div>
            </div>
            <button class="btn btn-primary" onclick="runPhase(1,this)">
              <div class="spinner"></div><span class="btn-text">▶ Run</span>
            </button>
          </div>
          <div class="phase-item">
            <div class="phase-info">
              <div class="phase-num">2</div>
              <div>
                <div class="phase-name">Publisher Bot</div>
                <div class="phase-desc">Sheet → Image → Make.com → Pinterest</div>
              </div>
            </div>
            <button class="btn btn-primary" onclick="runPhase(2,this)">
              <div class="spinner"></div><span class="btn-text">▶ Run</span>
            </button>
          </div>
          <div class="phase-item">
            <div class="phase-info">
              <div class="phase-num">3</div>
              <div>
                <div class="phase-name">Auto Refill Check</div>
                <div class="phase-desc">Check stock → Trigger Phase 1 if low</div>
              </div>
            </div>
            <button class="btn btn-primary" onclick="runPhase(3,this)">
              <div class="spinner"></div><span class="btn-text">▶ Run</span>
            </button>
          </div>
          <div class="phase-item">
            <div class="phase-info">
              <div class="phase-num">🚀</div>
              <div>
                <div class="phase-name">Full Daily Job</div>
                <div class="phase-desc">Phase 3 + Phase 2 together</div>
              </div>
            </div>
            <button class="btn btn-danger" onclick="runPhase('all',this)">
              <div class="spinner"></div><span class="btn-text">▶ Full Run</span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">📋 Live Logs</span>
        <button class="btn btn-ghost" onclick="clearLogs()">Clear</button>
      </div>
      <div class="panel-body" style="padding:14px">
        <div class="log-container" id="logContainer">
          <div class="log-line">
            <span class="log-time">--:--:--</span>
            <span class="log-level-info">INFO</span>
            <span class="log-msg">Dashboard ready...</span>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div class="panel products-panel">
    <div class="panel-header">
      <span class="panel-title">📦 Products in Sheet</span>
      <span style="font-size:12px;color:var(--muted);font-family:'Syne Mono',monospace" id="productCount">Loading...</span>
    </div>
    <div class="panel-body" style="padding:0">
      <div style="overflow-x:auto">
        <table>
          <thead>
            <tr><th>#</th><th>Product Name</th><th>Category</th><th>Gravity</th><th>Status</th></tr>
          </thead>
          <tbody id="productsTable">
            <tr><td colspan="5" style="text-align:center;color:var(--muted);padding:30px">Loading...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<div class="toast-wrap" id="toastWrap"></div>

<script>
const API = '';
function updateClock(){ document.getElementById('clock').textContent = new Date().toLocaleTimeString('en-IN'); }
setInterval(updateClock, 1000); updateClock();

function showToast(msg, type='success'){
  const w = document.getElementById('toastWrap');
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.innerHTML = `<span>${type==='success'?'✅':'❌'}</span><span>${msg}</span>`;
  w.appendChild(t); setTimeout(()=>t.remove(), 4000);
}

function addLog(msg, level='info'){
  const c = document.getElementById('logContainer');
  const time = new Date().toLocaleTimeString('en-IN');
  const colors = {info:'log-level-info',success:'log-level-success',error:'log-level-error',warn:'log-level-warn'};
  const d = document.createElement('div');
  d.className='log-line';
  d.innerHTML=`<span class="log-time">${time}</span><span class="${colors[level]||'log-level-info'}">${level.toUpperCase()}</span><span class="log-msg">${msg}</span>`;
  c.appendChild(d); c.scrollTop=c.scrollHeight;
}

function clearLogs(){ document.getElementById('logContainer').innerHTML=''; addLog('Logs cleared'); }

async function fetchStats(){
  try{
    const r = await fetch(`${API}/api/stats`);
    const d = await r.json();
    document.getElementById('statPending').textContent = d.pending??'--';
    document.getElementById('statPosted').textContent = d.posted_today??'--';
    document.getElementById('statTotal').textContent = d.total??'--';
    document.getElementById('statLastRun').textContent = d.last_run??'Never';
    const pill = document.getElementById('botStatus');
    const txt = document.getElementById('statusText');
    if(d.running){pill.className='status-pill running';txt.textContent='Running';}
    else{pill.className='status-pill stopped';txt.textContent='Online';}
  }catch(e){
    document.getElementById('statusText').textContent='Offline';
    document.getElementById('botStatus').className='status-pill stopped';
  }
}

async function fetchProducts(){
  try{
    const r = await fetch(`${API}/api/products`);
    const d = await r.json();
    const tbody = document.getElementById('productsTable');
    document.getElementById('productCount').textContent=`${d.products?.length??0} products`;
    if(!d.products?.length){
      tbody.innerHTML='<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:30px">No products yet — Run Phase 1!</td></tr>';
      return;
    }
    tbody.innerHTML=d.products.map((p,i)=>`
      <tr>
        <td style="color:var(--muted);font-family:'Syne Mono',monospace">${i+1}</td>
        <td style="font-weight:600">${p.product_name||'-'}</td>
        <td style="color:var(--muted)">${p.category||'-'}</td>
        <td style="font-family:'Syne Mono',monospace;color:var(--accent)">${p.gravity||'-'}</td>
        <td><span class="badge badge-${(p.Status||'').toLowerCase()==='posted'?'posted':'pending'}"><div class="badge-dot"></div>${p.Status||'PENDING'}</span></td>
      </tr>`).join('');
  }catch(e){
    document.getElementById('productsTable').innerHTML='<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:30px">Could not load</td></tr>';
  }
}

async function runPhase(phase, btn){
  btn.classList.add('loading'); btn.disabled=true;
  addLog(`Starting Phase ${phase}...`,'info');
  try{
    const r = await fetch(`${API}/api/run/${phase}`,{method:'POST'});
    const d = await r.json();
    if(d.status==='ok'){
      addLog(`Phase ${phase}: ${d.message}`,'success');
      showToast(`Phase ${phase} done! ${d.message}`);
      setTimeout(refreshAll,1500);
    }else{
      addLog(`Error: ${d.message}`,'error');
      showToast(`Error: ${d.message}`,'error');
    }
  }catch(e){
    addLog(`Failed: ${e.message}`,'error');
    showToast('Request failed','error');
  }
  btn.classList.remove('loading'); btn.disabled=false;
}

function refreshAll(){ fetchStats(); fetchProducts(); addLog('Refreshed','info'); }
fetchStats(); fetchProducts();
setInterval(fetchStats, 30000);
</script>
</body>
</html>
HTMLEOF

echo "🚀 Updating main.py with FastAPI..."
cat > main.py << 'EOF'
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
EOF

echo "🐳 Updating Dockerfile..."
cat > Dockerfile << 'EOF'
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 7860
CMD ["python", "main.py"]
EOF

echo "📤 Pushing to HuggingFace..."
git add .
git commit -m "dashboard UI + FastAPI + digistore integration"
git push origin main

echo ""
echo "✅ DONE! Check: https://huggingface.co/spaces/ksksysy540/pinteresto"
