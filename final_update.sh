#!/bin/bash
cd ~/pinteresto

echo "⚙️ Updating config.py..."
sed -i 's/DAILY_POST_LIMIT = 2/DAILY_POST_LIMIT = 1/' config.py

echo "🔧 Fixing Digistore API URL..."
cat > tools/digistore.py << 'EOF'
import httpx
import logging
from config import MAX_PRODUCTS_TO_FETCH, ALLOWED_CATEGORIES, BLOCKED_CATEGORIES

logger = logging.getLogger(__name__)

async def fetch_digistore_products(api_key: str) -> list:
    url = f"https://www.digistore24.com/api/call/listMarketplace/api_key/{api_key}/format/json/language/en"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url)
        data = response.json()
        logger.info(f"🔍 Result: {data.get('result')} | Message: {data.get('message')}")

        products_data = (
            data.get("data", {}).get("products") or
            data.get("data", {}).get("items") or []
        )
        logger.info(f"📦 Raw products: {len(products_data)}")

        normalized = []
        for p in products_data:
            category = str(p.get("category", "")).lower()
            if any(b in category for b in BLOCKED_CATEGORIES):
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

        logger.info(f"✅ Normalized: {len(normalized)} products")
        return normalized
    except Exception as e:
        logger.error(f"❌ Digistore error: {e}")
        return []
EOF

echo "🚀 Updating main.py — 9AM + 6PM, 1 pin each..."
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
from tools.google_drive import get_all_products

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

state = {"running": False, "last_run": None, "posted_today": 0}
scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")

async def daily_job():
    state["running"] = True
    state["last_run"] = datetime.now().strftime("%H:%M")
    logger.info("🚀 Job Started")
    try:
        await check_and_refill()
        posted = await run_publisher_bot()
        state["posted_today"] += posted
    finally:
        state["running"] = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(daily_job, "cron", hour=9, minute=0, id="morning")
    scheduler.add_job(daily_job, "cron", hour=18, minute=0, id="evening")
    scheduler.start()
    logger.info("✅ Scheduler — 9AM + 6PM IST | 1 pin each")
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
            return {"status": "ok", "message": f"{result} pin posted"}
        elif phase == "3":
            await check_and_refill()
            return {"status": "ok", "message": "Refill check done"}
        elif phase == "all":
            await check_and_refill()
            result = await run_publisher_bot()
            state["posted_today"] += result
            return {"status": "ok", "message": f"Full run done, {result} pin posted"}
        else:
            return {"status": "error", "message": "Invalid phase"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
EOF

echo "📤 Pushing to HuggingFace..."
git add .
git commit -m "final: 1 pin per slot, 9AM+6PM IST, digistore fix"
git push origin main

echo ""
echo "✅ DONE!"
echo "📌 Dashboard: https://ksksysy540-pinteresto.hf.space"
echo "⏰ Schedule: 9AM + 6PM IST — 1 pin each = 2 pins/day"
echo "📦 20 products = 10 din ka stock"
