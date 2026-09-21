"""
vision_run_once.py — GitHub Actions entrypoint for Vision Feeder.
run_feeder_agent() already handles daily limits via Vision_Tracker sheet
(restart-safe) — just call it once per cron trigger.
"""
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

from tools.visions_ai import run_feeder_agent


if __name__ == "__main__":
    result = run_feeder_agent()
    print(f"Vision Feeder result code: {result}")
