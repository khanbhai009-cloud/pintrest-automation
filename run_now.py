import asyncio
import logging
from agent import run_agent

# Logs on rakhte hain taaki GitHub Actions mein progress dikhe
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

async def start_mission():
    print("🚀 Pinteresto Bot Awakening...")
    
    # Account 1 Run (Home Decor)
    print("\n--- Running Account 1 (Home Decor) ---")
    await run_agent(trigger="scheduled-account1")
    
    # Account 2 Run (Tech)
    print("\n--- Running Account 2 (Tech) ---")
    await run_agent(trigger="scheduled-account2")
    
    print("\n✅ All tasks finished. Shutting down Cloud PC.")

if __name__ == "__main__":
    asyncio.run(start_mission())
  
