"""
sheets/ — Pinteresto ka dedicated Google Sheets layer.

Har file ka kaam:
  base.py           → connection helpers (_get_client, _open_worksheet, _get_spreadsheet)
  products.py       → Products tab CRUD (get_pending_products, mark_as_posted, save_products…)
  prompts_master.py → Prompts_Master tab fetch with 30-min TTL cache
  analytics.py      → Analytics_Log / Analytics_logs2 tab read
  style_tracker.py  → Style_Tracker tab: load/save style rotation indices
  prompt_tracker.py → Prompt_Tracker tab: load/save per-style prompt indices
  vision_tracker.py → Vision_Tracker tab: log processed images, get today's count
  setup.py          → init_sheets(): auto-create all required tabs on startup

Usage in other files:
  from sheets import get_prompts_master, load_style_tracker, save_style_tracker, ...
"""

from sheets.products       import (get_pending_products, mark_as_posted, save_products,
                                    count_pending, get_all_products,
                                    get_products_without_niche, update_niche)
from sheets.prompts_master import get_prompts_master, invalidate_cache, append_prompt_row
from sheets.analytics      import get_analytics_rows
from sheets.style_tracker  import load_style_tracker, save_style_tracker
from sheets.prompt_tracker import load_prompt_tracker, save_prompt_tracker
from sheets.vision_tracker import log_to_vision_tracker, get_today_count_from_sheet, get_all_processed_filenames
from sheets.setup          import init_sheets

__all__ = [
    # Products
    "get_pending_products", "mark_as_posted", "save_products",
    "count_pending", "get_all_products", "get_products_without_niche", "update_niche",
    # Prompts
    "get_prompts_master", "invalidate_cache", "append_prompt_row",
    # Analytics
    "get_analytics_rows",
    # Trackers
    "load_style_tracker", "save_style_tracker",
    "load_prompt_tracker", "save_prompt_tracker",
    "log_to_vision_tracker", "get_today_count_from_sheet", "get_all_processed_filenames",
    # Setup
    "init_sheets",
]
