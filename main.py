import asyncio
import logging
import os
from datetime import datetime

# ── Core Imports ─────────────────────────────────────────────────────────────
from mastermind.graph import run_mastermind
from sheets import init_sheets

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

async def run_engine():
    logger.info("🚀 Pinteresto v3 Engine Started (GitHub Actions Mode)")
    
    # ── 1. Auto-create missing Google Sheet tabs
    try:
        init_sheets()
    except Exception as e:
        logger.warning(f"⚠️ Sheet auto-init skipped — {e}")

    # ── 2. Read Manual Choice from GitHub
    # Agar cron se run hoga toh default 'both' uthayega
    choice = os.getenv("ACCOUNT_CHOICE", "both")
    
    if choice == "account1":
        trigger_val = "manual-account1"
        logger.info("🎯 Target: Run ONLY Account 1")
    elif choice == "account2":
        trigger_val = "manual-account2"
        logger.info("🎯 Target: Run ONLY Account 2")
    else:
        trigger_val = "manual-both"
        logger.info("🎯 Target: Run BOTH Accounts")

    # ── 3. Run the Mastermind Pipeline
    logger.info("🧠 Triggering Mastermind...")
    try:
        result = await run_mastermind(trigger=trigger_val)
        
        logger.info("✅ Pipeline Run Completed!")
        logger.info(f"📊 Summary: {result.get('summary', 'Done')}")
        logger.info(f"📌 A1 Posted: {result.get('a1_posted', False)}")
        logger.info(f"📌 A2 Posted: {result.get('a2_posted', False)}")
        
    except Exception as e:
        logger.error(f"❌ Error during Mastermind execution: {e}")

if __name__ == "__main__":
    asyncio.run(run_engine())

