import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from phases.phase1_filter import run_filter_bot
from phases.phase2_publish import run_publisher_bot
from phases.phase3_refill import check_and_refill

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# ADD NEW PHASES HERE IN FUTURE
# e.g. from phases.phase4_analytics import run_analytics
# ─────────────────────────────────────────

async def daily_job():
    logger.info("=" * 50)
    logger.info("🚀 Daily Job Started")
    logger.info("=" * 50)

    await check_and_refill()   # Phase 3: Restock if needed
    await run_publisher_bot()  # Phase 2: Post 2 pins

async def main():
    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
    
    # Runs every day at 9 AM IST
    scheduler.add_job(daily_job, "cron", hour=9, minute=0)
    scheduler.start()
    
    logger.info("✅ Bot is live. Waiting for scheduled jobs...")
    
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
