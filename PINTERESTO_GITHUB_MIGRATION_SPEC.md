# Pinteresto — HuggingFace → GitHub Actions Migration Spec

Give this whole file to Replit AI / Codespace AI as the task instructions. It already
analyzed the existing codebase (main.py, agent.py, graph.py, node_cmo.py, style_tracker.py,
state.py, base.py, config.py, visions_ai.py) — this spec is the exact diff needed.

---

## Goal

Stop running a persistent FastAPI + APScheduler server. Instead, GitHub Actions cron
triggers a short-lived script every run. Each run = one pin, decides account
automatically, exits in under a minute. No dashboard, no 24/7 process, no DNS issue
(fresh Ubuntu runner every time).

---

## 1. New file: `run_once.py` (repo root)

```python
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
```

---

## 2. New file: `vision_run_once.py` (repo root)

```python
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
```

---

## 3. Edit: `sheets/style_tracker.py`

Add a third column `next_turn` (string: `"account_1"` / `"account_2"`) to the SAME
existing `Style_Tracker` tab — NOT a new tab. This stores whose turn it is to post next.

Replace the whole file with:

```python
"""
sheets/style_tracker.py — Style rotation tracker (Style_Tracker sheet tab).

Tab columns: account_1 | account_2 | next_turn
Row 2 = current rotation indices (int) + whose turn is next (str).
Local JSON fallback: data/style_tracker_local.json

Reads are TTL-cached (5 min) to avoid hammering Sheets quota.
"""
import json
import logging
import os
import time
from sheets.base import _open_worksheet, _throttled_write, _throttled_read

logger = logging.getLogger(__name__)

_LOCAL_FILE = "data/style_tracker_local.json"

_read_cache: dict | None = None
_read_cache_ts: float    = 0.0
_READ_TTL = 300  # seconds


def _invalidate_cache() -> None:
    global _read_cache, _read_cache_ts
    _read_cache    = None
    _read_cache_ts = 0.0


def load_style_tracker() -> dict:
    """
    Load style rotation indices + turn state.
    Priority: in-memory TTL cache → Style_Tracker sheet tab → local JSON → empty dict.
    """
    global _read_cache, _read_cache_ts
    now = time.monotonic()

    if _read_cache is not None and (now - _read_cache_ts) < _READ_TTL:
        return dict(_read_cache)

    try:
        def _read():
            sheet = _open_worksheet("Style_Tracker")
            return sheet.get_all_records()

        records = _throttled_read(_read)
        if records:
            data = {}
            for k, v in records[0].items():
                if v == "":
                    continue
                data[k] = str(v) if k == "next_turn" else int(v)
            logger.info(f"✅ Style_Tracker loaded from Sheets: {data}")
            _read_cache    = data
            _read_cache_ts = now
            return dict(data)
    except Exception as e:
        logger.warning(f"Style_Tracker Sheet failed — {type(e).__name__}: {e} | trying local file")

    try:
        if os.path.exists(_LOCAL_FILE):
            with open(_LOCAL_FILE, "r") as f:
                data = json.load(f)
                logger.info(f"Style_Tracker loaded from local file: {data}")
                _read_cache    = data
                _read_cache_ts = now
                return dict(data)
    except Exception as e:
        logger.warning(f"Style_Tracker local file failed — {type(e).__name__}: {e} | starting from 0")

    return {}


def save_style_tracker(tracker: dict) -> None:
    """
    Save style rotation indices + turn state.
    Always writes local JSON first, then tries Sheets (best effort).
    NOTE: On GitHub Actions the local JSON does NOT persist across runs
    (fresh runner every time) — Sheets is the real source of truth.
    """
    _invalidate_cache()

    try:
        os.makedirs(os.path.dirname(_LOCAL_FILE), exist_ok=True)
        with open(_LOCAL_FILE, "w") as f:
            json.dump(tracker, f, indent=2)
    except Exception as e:
        logger.error(f"Style_Tracker local save failed — {type(e).__name__}: {e}")

    try:
        def _write():
            sheet    = _open_worksheet("Style_Tracker")
            records  = sheet.get_all_records()
            a1_val   = tracker.get("account_1", 0)
            a2_val   = tracker.get("account_2", 0)
            turn_val = tracker.get("next_turn", "account_1")
            if not records:
                sheet.append_row(["account_1", "account_2", "next_turn"])
                sheet.append_row([a1_val, a2_val, turn_val])
            else:
                headers = sheet.row_values(1)
                if "next_turn" not in headers:
                    sheet.update_cell(1, 3, "next_turn")
                sheet.update("A2", [[a1_val, a2_val, turn_val]])

        _throttled_write(_write)
        logger.info(f"✅ Style_Tracker saved to Sheets: {tracker}")
    except Exception as e:
        logger.warning(f"Style_Tracker Sheet save failed (local saved) — {type(e).__name__}: {e}")
```

---

## 4. Edit: `mastermind/state.py`

Add one field to `MastermindState`:

```python
    # ── V6 GitHub Actions turn-based scheduling ────────────────────────────
    target_account: Optional[str]  # "account_1" or "account_2" — decided by node_cmo_mastermind
```

---

## 5. Edit: `mastermind/node_cmo.py`

At the top of `node_cmo_mastermind`, replace the trigger-parsing block with turn logic.

Add this helper function anywhere above `node_cmo_mastermind`:

```python
def _decide_turn() -> str:
    """
    Reads next_turn from Style_Tracker, flips it, saves back.
    Returns which account should post THIS cycle.
    """
    tracker = load_style_tracker()
    turn = tracker.get("next_turn", "account_1")
    tracker["next_turn"] = "account_2" if turn == "account_1" else "account_1"
    save_style_tracker(tracker)
    return turn
```

Replace the start of `node_cmo_mastermind`:

```python
async def node_cmo_mastermind(state: MastermindState) -> dict:
    trigger = state.get("cycle_trigger", "")

    # Explicit override (manual trigger with "account1"/"account2" in string) still works
    explicit_a1 = "account1" in trigger and "account2" not in trigger
    explicit_a2 = "account2" in trigger and "account1" not in trigger

    if explicit_a1:
        target = "account_1"
    elif explicit_a2:
        target = "account_2"
    else:
        # Generic/cron trigger — auto-alternate via Style_Tracker's next_turn column
        target = _decide_turn()

    run_a1 = (target == "account_1")
    run_a2 = (target == "account_2")

    label = "A1" if run_a1 else "A2"
    logger.info(f"[Node 2 - CMO] Turn-based v6 | target={label} | trigger={trigger}")

    # Log what's coming up next (peek without advancing)
    if run_a1:
        logger.info(f"   A1 next style: {_peek_current_style('account_1')}")
    if run_a2:
        logger.info(f"   A2 next style: {_peek_current_style('account_2')}")
```

(Keep everything below unchanged — a1_metrics, a2_metrics, boards, trends, the two
try/except blocks for a1_strategy/a2_strategy.)

At the very end of the function, add `target_account` to the returned dict:

```python
    return {
        "a1_cmo_strategy":    a1_strategy,
        "a2_cmo_strategy":    a2_strategy,
        "fallback_triggered": fallback,
        "target_account":     target,
    }
```

Also add this import at the top of the file (alongside the existing `from sheets import ...`):

```python
from sheets import load_style_tracker, save_style_tracker
```
(Already imported — just confirm both names are present in the existing import line.)

---

## 6. Edit: `mastermind/graph.py`

Replace the start of `node_agent_executor`:

```python
async def node_agent_executor(state: MastermindState) -> dict:
    target      = state.get("target_account")
    a1_strategy = state.get("a1_cmo_strategy", {})
    a2_strategy = state.get("a2_cmo_strategy", {})

    if target is not None:
        run_a1 = (target == "account_1")
        run_a2 = (target == "account_2")
    else:
        # Safety net — should not normally trigger since node_cmo always sets target_account
        trigger = state.get("cycle_trigger", "")
        only_a1 = "account1" in trigger and "account2" not in trigger
        only_a2 = "account2" in trigger and "account1" not in trigger
        run_a1  = not only_a2
        run_a2  = not only_a1

    trigger = state.get("cycle_trigger", "")
    logger.info(
        f"🤖 [Node 3 — Agent Executor] trigger={trigger} | target={target} | "
        f"run_a1={run_a1} run_a2={run_a2}"
    )
```

(Keep the rest of the function body exactly as-is — SKIPPED dict, a1_result/a2_result
logic, return dict.)

In `run_mastermind()`, add `"target_account": None,` to `initial_state` dict
(anywhere alongside the other fields).

---

## 7. Behavior change to be aware of

Before: a generic trigger (e.g. `"manual-both"` from the old dashboard) ran **both**
accounts in one call.
After: any trigger without `"account1"`/`"account2"` explicitly in it now runs
**exactly one** account, auto-alternating via `next_turn`. This is intentional —
GitHub cron will call `run_once.py` repeatedly, and each call should post once.

---

## 8. New file: `.github/workflows/pin_scheduler.yml`

```yaml
name: Pinteresto Pin Scheduler

on:
  schedule:
    - cron: '0 * * * *'   # every hour — GitHub cron can't express "random 60-72 min gap"
  workflow_dispatch: {}     # manual trigger button in Actions tab

jobs:
  run-pin:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python run_once.py
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          CEREBRAS_API_KEY: ${{ secrets.CEREBRAS_API_KEY }}
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
          IMGBB_API_KEY: ${{ secrets.IMGBB_API_KEY }}
          GOOGLE_CREDS_JSON: ${{ secrets.GOOGLE_CREDS_JSON }}
          SPREADSHEET_ID: ${{ secrets.SPREADSHEET_ID }}
          RAPIDAPI_KEY: ${{ secrets.RAPIDAPI_KEY }}
          RAPIDAPI_KEY2: ${{ secrets.RAPIDAPI_KEY2 }}
          TAVILY_API_KEY: ${{ secrets.TAVILY_API_KEY }}
          CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          GEMINI_API_KEY_2: ${{ secrets.GEMINI_API_KEY_2 }}
          FIREBASE_CREDS_JSON: ${{ secrets.FIREBASE_CREDS_JSON }}
          MAKE_WEBHOOK_URL: ${{ secrets.MAKE_WEBHOOK_URL }}
          MAKE_WEBHOOK_URL_2: ${{ secrets.MAKE_WEBHOOK_URL_2 }}
```

**Important honest caveat:** standard cron syntax cannot express "random 60-72 min
gap" — that was only possible because APScheduler pre-computed randomized future
timestamps in Python. GitHub Actions cron is fixed-schedule only. Options:
- **Simplest (used above):** fixed hourly cadence (`0 * * * *`). Loses randomness,
  gains reliability. Also note GitHub cron has soft delays of 5-15 min under load
  regardless.
- **If randomness matters to you:** add a 4th column `last_run_ts` to Style_Tracker,
  set cron to run every 20 min, and at the top of `run_once.py` read the timestamp,
  compute a random threshold (60-72 min), and `exit(0)` early if not enough time has
  passed. Say the word and I'll spec this out too.

---

## 9. New file: `.github/workflows/vision_feeder.yml`

```yaml
name: Pinteresto Vision Feeder

on:
  schedule:
    - cron: '0 */2 * * *'   # every 2 hours — matches old 1-hour-sleep loop roughly
  workflow_dispatch: {}

jobs:
  run-vision:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python vision_run_once.py
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          GEMINI_API_KEY_2: ${{ secrets.GEMINI_API_KEY_2 }}
          GOOGLE_CREDS_JSON: ${{ secrets.GOOGLE_CREDS_JSON }}
          SPREADSHEET_ID: ${{ secrets.SPREADSHEET_ID }}
```

---

## 10. GitHub Secrets checklist (Settings → Secrets and variables → Actions)

Confirm these all exist (from `config.py`):

- `GROQ_API_KEY`
- `CEREBRAS_API_KEY`
- `OPENROUTER_API_KEY`
- `IMGBB_API_KEY`
- `GOOGLE_CREDS_JSON`
- `SPREADSHEET_ID`
- `RAPIDAPI_KEY`
- `RAPIDAPI_KEY2`
- `TAVILY_API_KEY`
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`
- `GEMINI_API_KEY`
- `GEMINI_API_KEY_2`
- `FIREBASE_CREDS_JSON`
- `MAKE_WEBHOOK_URL`
- `MAKE_WEBHOOK_URL_2`

---

## 11. `requirements.txt` — no change needed

`fastapi`, `uvicorn`, `gunicorn`, `apscheduler` are now unused by `run_once.py`/
`vision_run_once.py` but harmless to leave (just a few extra seconds of install
time). Safe to remove later if you want faster CI, not required now.

---

## 12. `main.py` — leave untouched in the repo

Not deleted, just not run by GitHub Actions. If you ever want the old dashboard
back (e.g. self-hosted elsewhere), it still works standalone.

---

## Files NOT touched (confirmed compatible as-is)

- `agent.py` — `run_agent()`, `publish_next_pin()` — zero changes needed
- `sheets/base.py`, `sheets/products.py`, `sheets/prompts_master.py`,
  `sheets/analytics.py`, `sheets/prompt_tracker.py`, `sheets/vision_tracker.py`,
  `sheets/setup.py` — zero changes needed
- `tools/visions_ai.py` — zero changes needed (already restart-safe via
  Vision_Tracker sheet)
