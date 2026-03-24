import logging
import random
import time
from typing import Annotated
from typing_extensions import TypedDict
from langchain_groq import ChatGroq
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from tools.google_drive import (
    count_pending, get_pending_products, save_products,
    mark_as_posted, get_products_without_niche, update_niche
)
from tools.groq_ai import filter_product, generate_pin_copy
from tools.make_webhook import post_to_pinterest
from tools.aliexpress import search_products, KEYWORDS_BY_NICHE, DEFAULT_KEYWORDS
from tools.admitad import enrich_with_affiliate_link
from utils.image_processor import process_product_image
from tools.llm import chat
from config import GROQ_API_KEY, GROQ_MODEL, PINTEREST_ACCOUNTS

logger = logging.getLogger(__name__)

CURRENT_TRIGGER = None

class BotState(TypedDict):
    messages:     Annotated[list, add_messages]
    posted_count: int
    refilled:     bool
    errors:       list[str]

account_niches = [a["niche"] for a in PINTEREST_ACCOUNTS]

@tool
def fill_missing_niches() -> dict:
    """
    Scan Google Sheet for products with empty niche column.
    Use AI to detect correct niche from product name + keyword.
    Call ONCE at the start of every run.
    """
    products = get_products_without_niche()
    if not products:
        return {"updated": 0, "message": "All products already have niche set ✅"}

    VALID_NICHES = [
        "home", "kitchen", "cozy", "gadgets", "organize",
        "tech", "budget", "phone", "smarthome", "wfh"
    ]
    updated = 0

    for p in products:
        name    = p.get("product_name", "")
        keyword = p.get("keyword", "")
        prompt = f"""You are a categorization expert. Product: {name}. Keyword: {keyword}. Available niches: {VALID_NICHES}. Choose SINGLE best exact match. Nothing else."""
        try:
            niche = chat(prompt, temperature=0.1).strip().lower()
            if niche not in VALID_NICHES:
                niche = "home"
            update_niche(name, niche)
            updated += 1
            logger.info(f"🏷️ Niche set: {name[:60]} → {niche}")
            time.sleep(2.5) # Protects Google Sheets API quota
        except Exception as e:
            logger.error(f"❌ Niche detect failed: {name[:30]} — {e}")
            time.sleep(2.5)

    return {"updated": updated, "total": len(products), "message": f"✅ {updated}/{len(products)} niches filled"}

@tool
def analyze_niche_stock() -> dict:
    """
    AI selects a specific sub-niche (board) to post to today based on the triggered account.
    Checks if that specific board has enough stock.
    Call ONCE after filling niches.
    """
    global CURRENT_TRIGGER
    if CURRENT_TRIGGER in ["manual-account1", "scheduled-account1"]:
        allowed_niches = ["home", "kitchen", "cozy", "gadgets", "organize"]
    else:
        allowed_niches = ["tech", "budget", "phone", "smarthome", "wfh"]

    chosen_niche = random.choice(allowed_niches)
    pending = get_pending_products(limit=50, allowed_niches=[chosen_niche])
    count = len(pending)
    
    logger.info(f"🎯 AI Selected Board Niche: '{chosen_niche}' | Stock: {count}")
    return {"selected_niche": chosen_niche, "stock_count": count, "needs_fetching": count == 0}

@tool
async def fetch_aliexpress_products(niche: str) -> dict:
    """
    Fetch trending AliExpress products strictly for the selected niche.
    Call ONCE only if analyze_niche_stock says needs_fetching is true.
    """
    niche_keywords = KEYWORDS_BY_NICHE.get(niche, DEFAULT_KEYWORDS)
    keyword = random.choice(niche_keywords) if niche_keywords else "trending"

    logger.info(f"🛒 Stock empty! Fetching new products for: '{niche}' (Keyword: {keyword})")
    raw = await search_products(keyword=keyword, max_results=20, niche=niche)
    if not raw: 
        return {"approved": 0, "fetched": 0, "error": "AliExpress returned 0 products. Do NOT retry."}

    linked   = [enrich_with_affiliate_link(p) for p in raw]
    approved = [p for p in linked if filter_product(p)]
    if approved: save_products(approved)
    
    return {"keyword": keyword, "niche": niche, "fetched": len(raw), "approved": len(approved)}

@tool
async def publish_next_pin(niche: str) -> dict:
    """
    Get next PENDING product for the specific niche, generate viral copy, and publish.
    Call ONCE.
    """
    global CURRENT_TRIGGER
    target_account = "Account1_HomeDecor" if "account1" in str(CURRENT_TRIGGER) else "Account2_Tech"

    pending = get_pending_products(limit=1, allowed_niches=[niche])
    if not pending:
        return {"success": False, "reason": f"Still no products for niche: {niche}"}

    product = pending[0]
    name    = product.get("product_name", "Unknown")

    try:
        copy        = generate_pin_copy(product)
        title       = copy.get("title", name)
        description = copy.get("description", "")
        tags        = copy.get("tags", [])

        image_bytes = await process_product_image(product.get("image_url", ""), title)
        if not image_bytes: return {"success": False, "reason": "Image processing failed"}

        success = await post_to_pinterest(
            image_url=product.get("image_url"), title=title, description=description,
            link=product.get("affiliate_link"), tags=tags, niche=niche,
            target_account=target_account
        )

        if success:
            mark_as_posted(name)
            logger.info(f"🎉 Posted: {name[:40]}... [{niche}] to {target_account}!")
            return {"success": True, "product": name, "title": title, "niche": niche}
        return {"success": False, "reason": "Webhook failed"}

    except Exception as e:
        logger.error(f"❌ publish error: {e}")
        return {"success": False, "reason": str(e)}

ALL_TOOLS = [fill_missing_niches, analyze_niche_stock, fetch_aliexpress_products, publish_next_pin]

llm = ChatGroq(api_key=GROQ_API_KEY, model=GROQ_MODEL, temperature=0.1).bind_tools(ALL_TOOLS)


# 🔥 TUMHARA ELITE SYSTEM PROMPT (UPDATED FOR NEW LOGIC) 🔥
SYSTEM_PROMPT = f"""You are PINTERESTO — an elite autonomous Pinterest affiliate marketing bot engineered for maximum revenue generation. You manage {len(PINTEREST_ACCOUNTS)} Pinterest business accounts.

You think like a Senior Growth Hacker + Affiliate Marketing Director with 10+ years experience. Every decision you make is calculated, efficient, and revenue-focused. You do not guess. You do not retry. You do not loop.

═══════════════════════════════════════
EXECUTION PROTOCOL — FOLLOW EXACTLY
═══════════════════════════════════════

STEP 1 → fill_missing_niches()
- Call ONCE at the start of every run.
- Ensures every product in sheet has correct niche mapping.

STEP 2 → analyze_niche_stock()
- Call ONCE.
- AI will select a target board (niche) and check its inventory.
- Returns 'selected_niche' and a boolean 'needs_fetching'.

STEP 3 → fetch_aliexpress_products(niche="<selected_niche>") [ONLY if needs_fetching=true]
- Call ONCE using the exact niche returned from Step 2.
- If it returns 0 approved or an error → STOP immediately, go to END. Do NOT retry.

STEP 4 → publish_next_pin(niche="<selected_niche>")
- Call ONCE using the exact niche returned from Step 2.
- Posts to correct board via Make.com webhook.
- Marks product as POSTED in sheet.

STEP 5 → END
- Write summary in exact format below.
- Stop all execution.

═══════════════════════════════════════
HARD RULES — NEVER VIOLATE
═══════════════════════════════════════
❌ NEVER call any single tool more than once per run.
❌ NEVER retry on empty results or errors.
❌ NEVER loop back after a failure.
❌ NEVER invent product data.
❌ NEVER skip the summary — always end with exact format.

═══════════════════════════════════════
DECISION LOGIC
═══════════════════════════════════════
IF analyze_niche_stock returns needs_fetching=false:
  → Skip Step 3, go directly to Step 4.

IF fetch returns approved=0:
  → Skip Step 4, go directly to END with Status: Partial.

IF publish returns success=false:
  → Log reason, go to END with Status: Partial.

═══════════════════════════════════════
MANDATORY END FORMAT
═══════════════════════════════════════
NICHES FILLED: [X products updated] OR "None needed"
TARGET BOARD: "[selected_niche]"
FETCHED: [X approved] via "[keyword]" OR "Skipped — stock sufficient" OR "Failed"
POSTED: "[product title]" → [niche] board OR "Skipped" OR "Failed — [reason]"
STATUS: Success / Partial / Failed"""


async def agent_node(state: BotState) -> dict:
    if len(state["messages"]) > 14:
        logger.warning("⚠️ Max messages reached — forcing END")
        from langchain_core.messages import AIMessage
        return {"messages": [AIMessage(
            content="NICHES FILLED: Unknown\nTARGET BOARD: Unknown\nFETCHED: Unknown\nPOSTED: Stopped — loop guard triggered\nSTATUS: Failed"
        )]}
    logger.info(f"🧠 Agent thinking... ({len(state['messages'])} messages)")
    response = await llm.ainvoke(state["messages"])
    logger.info(f"🔧 Tool calls: {len(response.tool_calls) if hasattr(response, 'tool_calls') else 0}")
    return {"messages": [response]}

def should_continue(state: BotState) -> str:
    last      = state["messages"][-1]
    has_tools = hasattr(last, "tool_calls") and len(last.tool_calls) > 0
    logger.info(f"🔀 Routing → {'tools' if has_tools else 'END'}")
    return "tools" if has_tools else END

def build_agent():
    g = StateGraph(BotState)
    g.add_node("agent", agent_node)
    g.add_node("tools", ToolNode(ALL_TOOLS))
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()

async def run_agent(trigger: str = "scheduled") -> dict:
    global CURRENT_TRIGGER
    CURRENT_TRIGGER = trigger
    logger.info(f"🤖 Agent started — {trigger}")
    agent       = build_agent()
    final_state = await agent.ainvoke({
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=f"Run Pinterest bot cycle. Trigger: {trigger}"),
        ],
        "posted_count": 0, "refilled": False, "errors": [],
    })
    summary = getattr(final_state["messages"][-1], "content", "Done")
    logger.info(f"✅ Agent done:\n{summary}")
    return {"status": "ok", "summary": summary, "trigger": trigger}
