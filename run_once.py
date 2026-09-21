"""
run_once.py — GitHub Actions entrypoint. One run = one pin cycle.
Account selection (account_1 vs account_2) is now decided INSIDE
mastermind/node_cmo.py using the Style_Tracker sheet's "next_turn" column —
no external state needed here.
"""
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

from mastermind.graph import run_mastermind


async def main():
    result = await run_mastermind(trigger="scheduled")
    print(result.get("summary", result))


if __name__ == "__main__":
    asyncio.run(main())
