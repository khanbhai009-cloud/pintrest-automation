import logging
import random
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
from config import (
    GROQ_API_KEY, GROQ_MODEL, LOW_STOCK_THRESHOLD,
    DAILY_POST_LIMIT, PINTEREST_ACCOUNTS
)

logger = logging.getLogger(__name__)

# ── State ───────────────────────────────────────────────────
class BotState(TypedDict):
    messages:     Annotated[list, add_messages]
    posted_count: int
    refilled:     bool
    errors:       list[str]

# ── Account niches for prompt ───────────────────────────────
account_niches = [a["niche"] for a in PINTEREST_ACCOUNTS]

# ── Tools ───────────────────────────────────────────────────

@tool
def fill_missing_niches() -> dict:
    """
    Scan Google Sheet for products with empty niche column.
    Use AI to detect correct niche from product name + keyword.
    Update sheet automatically.
    Call ONCE at the start of every run.
    """
    products = get_products_without_niche()
    if not products:
        return {"updated": 0, "message": "All products already have niche set ✅"}

    VALID_NICHES = ["home", "tech", "fashion", "fitness", "beauty"]
    updated = 0

    for p in products:
        name    = p.get("product_name", "")
        keyword = p.get("keyword", "")

        prompt = f"""You are a product categorization expert for Pinterest affiliate marketing.

Analyze this product and assign it to exactly one niche category.

Product name: {name}
Search keyword used: {keyword}

Available niches: {VALID_NICHES}

Category definitions:
- home    = home decor, kitchen tools, room accessories, lighting, furniture, organization, cleaning
- tech    = gadgets, phone accessories, laptop gear, electronics, chargers, earbuds, smart devices
- fashion = clothing, bags, jewelry, accessories, sunglasses, watches, hair accessories
- fitness = gym equipment, workout gear, yoga, sports, massage tools, resistance bands
- beauty  = skincare, makeup, hair care, nail tools, face devices, glow/wellness products

Rules:
- Choose the SINGLE best matching niche
- If ambiguous, pick the closest match
- Respond with ONLY one word from the list — nothing else, no punctuation

Your answer:"""

        try:
            niche = chat(prompt, temperature=0.1).strip().lower()
            if niche not in VALID_NICHES:
                niche = "home"  # safe fallback
            update_niche(name, niche)
            updated += 1
            logger.info(f"🏷️ Niche set: {name[:60]} → {niche}")
        except Exception as e:
            logger.error(f"❌ Niche detect failed: {name} — {e}")

    return {
        "updated": updated,
        "total":   len(products),
        "message": f"✅ {updated}/{len(products)} products niche updated"
    }


@tool
def check_stock() -> dict:
    """Check how many PENDING products remain in Google Sheets."""
    count = count_pending()
    logger.info(f"📊 Stock: {count} pending")
    return {"pending_count": count, "low_stock": count <= LOW_STOCK_THRESHOLD}


@tool
async def fetch_aliexpress_products(
    keyword: str  = "",
    niche: str    = "home",
    max_items: int = 20
) -> dict:
    """
    Fetch trending AliExpress products by niche.
    Enrich with Admitad affiliate links.
    Filter with AI. Save approved products to Google Sheets.
    Call ONCE when stock is low. Do NOT retry on 0 results.
    """
    if not keyword:
        niche_keywords = KEYWORDS_BY_NICHE.get(niche, DEFAULT_KEYWORDS)
        keyword        = random.choice(niche_keywords)

    logger.info(f"🛒 [{niche}] Fetching: '{keyword}'")
    raw = await search_products(keyword=keyword, max_results=max_items, niche=niche)

    if not raw:
        return {
            "approved": 0, "fetched": 0,
            "keyword":  keyword, "niche": niche,
            "error":    "AliExpress returned 0 products. Do NOT retry. Report in summary."
        }

    linked   = [enrich_with_affiliate_link(p) for p in raw]
    approved = [p for p in linked if filter_product(p)]

    if approved:
        save_products(approved)

    logger.info(f"✅ Saved {len(approved)}/{len(raw)} [{niche}]")
    return {
        "keyword":  keyword,
        "niche":    niche,
        "fetched":  len(raw),
        "approved": len(approved)
    }


@tool
async def publish_next_pin() -> dict:
    """
    Get next PENDING product from sheet.
    Generate viral Pinterest copy with AI.
    Post via Make.com to correct niche board.
    Mark product as POSTED in sheet.
    Call ONCE per run.
    """
    pending = get_pending_products(limit=1)
    if not pending:
        return {"success": False, "reason": "No pending products in sheet"}

    product = pending[0]
    name    = product.get("product_name", "Unknown")
    niche   = product.get("niche", "default")

    try:
        copy        = generate_pin_copy(product)
        title       = copy.get("title", name)
        description = copy.get("description", "")
        tags        = copy.get("tags", [])

        image_bytes = await process_product_image(product.get("image_url", ""), title)
        if not image_bytes:
            return {"success": False, "reason": f"Image processing failed: {name}"}

        success = await post_to_pinterest(
            image_url=product.get("image_url"),
            title=title,
            description=description,
            link=product.get("affiliate_link"),
            tags=tags,
            niche=niche,
        )

        if success:
            mark_as_posted(name)
            logger.info(f"🎉 Posted: {name} [{niche}]")
            return {"success": True, "product": name, "title": title, "niche": niche}

        return {"success": False, "reason": f"Webhook failed: {name}"}

    except Exception as e:
        logger.error(f"❌ publish error: {e}")
        return {"success": False, "reason": str(e)}


# ── LLM + Tools Setup ───────────────────────────────────────
ALL_TOOLS = [fill_missing_niches, check_stock, fetch_aliexpress_products, publish_next_pin]

llm = ChatGroq(
    api_key=GROQ_API_KEY,
    model=GROQ_MODEL,
    temperature=0.1,
).bind_tools(ALL_TOOLS)


# ── System Prompt ───────────────────────────────────────────
SYSTEM_PROMPT = f"""You are PINTERESTO — an elite autonomous Pinterest affiliate marketing engineered for maximum revenue generation. You manage {len(PINTEREST_ACCOUNTS)} Pinterest business accounts across niches: {account_niches}.

You think like a Senior Growth Hacker + Affiliate Marketing Director with 10+ years experience. Every decision you make is calculated, efficient, and revenue-focused. You do not guess. You do not retry. You do not loop.

═══════════════════════════════════════
EXECUTION PROTOCOL — FOLLOW EXACTLY
═══════════════════════════════════════

STEP 1 → fill_missing_niches()
- Call ONCE at the start of every run
- Ensures every product in sheet has correct niche mapping
- If 0 products need updating → log and move on immediately

STEP 2 → check_stock()
- Call ONCE
- Returns pending_count and low_stock flag

STEP 3 → fetch_aliexpress_products() [ONLY if low_stock=true]
- Call ONCE with a niche from {account_niches}
- Rotate niches — do NOT always pick the same one
- If returns approved=0 or contains error → STOP immediately, go to END
- Do NOT retry. Do NOT call with different keyword. ONE call maximum.

STEP 4 → publish_next_pin()
- Call ONCE
- Picks next PENDING product from sheet
- AI generates viral Pinterest copy
- Posts to correct board via Make.com webhook
- Marks product as POSTED in sheet

STEP 5 → END
- Write summary in exact format below
- Stop all execution

═══════════════════════════════════════
HARD RULES — NEVER VIOLATE
═══════════════════════════════════════
❌ NEVER call any single tool more than once per run
❌ NEVER retry on empty results or errors
❌ NEVER loop back after a failure
❌ NEVER hallucinate tool calls or invent product data
❌ NEVER skip the summary — always end with exact format

═══════════════════════════════════════
DECISION LOGIC
═══════════════════════════════════════
IF fill_missing_niches returns updated > 0:
  → Log how many were updated, continue to Step 2

IF check_stock returns low_stock=false:
  → Skip Step 3, go directly to Step 4

IF fetch returns approved=0:
  → Skip Step 4, go directly to END with Status: Partial

IF publish returns success=false:
  → Log reason, go to END with Status: Partial

IF all steps succeed:
  → END with Status: Success

═══════════════════════════════════════
MANDATORY END FORMAT
═══════════════════════════════════════
NICHES FILLED: [X products updated] OR "None needed"
FETCHED: [X approved / Y total] via "[keyword]" ([niche]) OR "Skipped — stock sufficient" OR "Failed — 0 results"
POSTED: "[product name]" → [niche] board OR "Skipped" OR "Failed — [reason]"
STATUS: Success / Partial / Failed"""


# ── Agent Nodes ─────────────────────────────────────────────
async def agent_node(state: BotState) -> dict:
    if len(state["messages"]) > 14:
        logger.warning("⚠️ Max messages reached — forcing END")
        from langchain_core.messages import AIMessage
        return {"messages": [AIMessage(
            content="NICHES FILLED: Unknown\nFETCHED: Unknown\nPOSTED: Stopped — loop guard triggered\nSTATUS: Failed"
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
    logger.info(f"✅ Agent done: {summary}")
    return {"status": "ok", "summary": summary, "trigger": trigger}
