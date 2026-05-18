"""
mastermind/node_cmo.py — Node 2: CMO Mastermind  [ELITE VISUAL UPGRADE v6 — SEQUENTIAL ROTATION]

STRATEGY : 100% VIRAL_PIN — ultra-realistic, editorial-grade aesthetic AI images only.
PRIMARY  : Gemini 2.5 Flash  (JSON mode forced via response_mime_type)
FALLBACK : Cerebras qwen-3-235b  (429 = no retry, skip to hardcoded immediately)
HARDCODED: Last-resort static strategy keeps pipeline alive

ROTATION ENGINE (NEW):
  • Cycles through ALL visual styles one by one across runs
  • No style is repeated until all others are covered
  • Tracker stored in: data/style_tracker.json (persists on HuggingFace Spaces)
  • Run 1 → style[0] for A1, style[0] for A2
  • Run 2 → style[1] for A1, style[1] for A2
  • ...and so on, covering full variety automatically

Visual Styles (16):
  HOME DECOR ACCOUNT (account_1) — bright, colorful, modern Pinterest-viral aesthetic:
  1. Boho Aesthetic Study        — warm plants, gallery wall, rattan, golden morning light, art prints
  2. Sunflower Yellow Porch      — white wicker, sunflowers, yellow checkered rug, hanging baskets
  3. Pastel Dreamy Kitchen       — mint green + pink, cherry blossoms, copper pendant, strawberries
  4. Sage Copper Dining Room     — sage walls, copper dome lights, yellow daffodils, mid-century chairs
  5. Vintage Wildflower Drive    — yellow VW Beetle, pink wildflower field, snow mountain backdrop
  6. Jungle Biophilic Bedroom    — ceiling vines, floor-level bed, mint comforter, glass walls, daylight
  7. Yellow Kawaii Bedroom       — LED underglow bed, plushies, warm wood built-ins, cozy golden glow
  8. Golden Balcony Garden       — cozy wicker sofa, yellow sunflowers, checkered rug, dappled sunlight
  9. Yellow Floral Caravan       — sunshine yellow barrel-roof caravan, chrysanthemums, fairy lights, deck
  10. Mint Cottage Garden        — mint green storybook cottage, white hydrangeas, oval stepping stones
  11. Lantern Fairytale Treehouse— glowing cottages under ancient tree, hanging lanterns, waterside dusk

  TECH ACCOUNT (account_2) — Pinterest-viral aesthetic, NOT cyberpunk:
  12. Kawaii Pastel Gaming Setup  — lavender hex panels, transparent keyboard, Sanrio, sakura lights
  13. Cottagecore Tech Den        — ivy walls, Minecraft desk, sage keycaps, mushroom ceramics, fantasy books
  14. Sage Clean Workspace        — mint iMac, green keyboard, daisy vase, yellow lamp, K-aesthetic flat lay
  15. Warm Minimalist Bedside Tech— white nightstand, smart clock+charger, amber glow, reed diffuser, wood panels
  16. Yellow Creator Flat Lay     — yellow headphones + MacBook + DSLR camera + roses, overhead, warm golden light

Ratio per pin: randomly chosen — 9:16 portrait OR 1:1 square (70/30 split)
"""
import asyncio
import json
import logging
import os
import random
import re
from config import CEREBRAS_API_KEY, CEREBRAS_CMO_MODEL, GEMINI_API_KEY, GEMINI_CMO_MODEL
from mastermind.state import MastermindState
from sheets import (get_prompts_master, load_style_tracker, save_style_tracker,
                    load_prompt_tracker, save_prompt_tracker)

logger = logging.getLogger(__name__)

# ── Gemini client ──────────────────────────────────────────────────────────────
try:
    from google import genai as _genai
    from google.genai import types as _gtypes
    _gemini_client = _genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
except Exception:
    _gemini_client = None

# ── Cerebras client ────────────────────────────────────────────────────────────
try:
    from cerebras.cloud.sdk import Cerebras as _Cerebras
    _cerebras_client = _Cerebras(api_key=CEREBRAS_API_KEY) if CEREBRAS_API_KEY else None
except Exception:
    _cerebras_client = None

# ── Image ratio config ─────────────────────────────────────────────────────────
_RATIOS = {
    "9:16": {"label": "9:16 tall portrait", "w": 1080, "h": 1920},
    "1:1":  {"label": "1:1 square",          "w": 1080, "h": 1080},
}

def _pick_ratio() -> str:
    """70% portrait (9:16), 30% square (1:1) — portrait dominates Pinterest feed."""
    return random.choices(["9:16", "1:1"], weights=[70, 30], k=1)[0]


# ══════════════════════════════════════════════════════════════════════════════
# SEQUENTIAL ROTATION ENGINE
# Cycles through ALL styles one by one. Tracker saved to JSON file.
# ══════════════════════════════════════════════════════════════════════════════

# Ordered style rotation lists per account — all styles covered in sequence
ACCOUNT_1_STYLE_ORDER = [
    "boho_aesthetic_study",
    "sunflower_yellow_porch",
    "pastel_dreamy_kitchen",
    "sage_copper_dining",
    "vintage_wildflower_drive",
    "jungle_biophilic_bedroom",
    "yellow_kawaii_bedroom",
    "golden_balcony_garden",
    "yellow_floral_caravan",
    "mint_cottage_garden",
    "lantern_fairytale_treehouse",
]

ACCOUNT_2_STYLE_ORDER = [
    "kawaii_pastel_gaming",
    "cottagecore_tech_den",
    "sage_clean_workspace",
    "warm_minimalist_bedside",
    "yellow_creator_flatlay",
]

_ACCOUNT_STYLE_ORDERS = {
    "account_1": ACCOUNT_1_STYLE_ORDER,
    "account_2": ACCOUNT_2_STYLE_ORDER,
}


def _get_sheet_style_order(account_key: str) -> list | None:
    """
    Dynamically fetch unique style_keys for this account from Prompts_Master sheet.
    Order preserved as-is from the sheet (top → bottom).
    Auto-scales: new styles added to the sheet appear within 30 min (TTL cache).
    Returns None if Sheets unavailable → caller uses hardcoded lists.
    """
    try:
        rows = get_prompts_master()
        seen = []
        for row in rows:
            sk  = str(row.get("style_key", "")).strip()
            acc = str(row.get("account", "")).strip()
            if sk and acc == account_key and sk not in seen:
                seen.append(sk)
        return seen if seen else None
    except Exception as e:
        logger.warning(f"[{account_key}] Sheet style order failed — {type(e).__name__}: {e}")
        return None


def _get_effective_style_order(account_key: str) -> list:
    """Sheets style list (auto-scale) → hardcoded fallback."""
    return _get_sheet_style_order(account_key) or _ACCOUNT_STYLE_ORDERS[account_key]


def _get_next_style(account_key: str) -> str:
    """
    Returns the NEXT style in rotation for this account.
    Source priority: Prompts_Master sheet (auto-scale) → hardcoded ACCOUNT_STYLE_ORDERS.
    Wraps back to index 0 after all styles covered.
    """
    order    = _get_effective_style_order(account_key)
    tracker  = load_style_tracker()
    last_idx = tracker.get(account_key, -1)
    next_idx = (last_idx + 1) % len(order)

    tracker[account_key] = next_idx
    save_style_tracker(tracker)

    chosen = order[next_idx]
    logger.info(f"   [{account_key}] Style Rotation [{next_idx+1}/{len(order)}] → {chosen}")
    return chosen


def _peek_current_style(account_key: str) -> str:
    """Peek at NEXT style WITHOUT advancing any tracker (for logging/dashboard)."""
    order    = _get_effective_style_order(account_key)
    tracker  = load_style_tracker()
    idx      = tracker.get(account_key, -1)
    curr_idx = (idx + 1) % len(order)
    return order[curr_idx]


# ══════════════════════════════════════════════════════════════════════════════
# PROMPTS_MASTER SHEET — Fetch + Rotate prompts per account/style
# Fallback: hardcoded VISUAL_STYLES t2i_base if Sheets unavailable
# ══════════════════════════════════════════════════════════════════════════════



def _get_sheet_row_for_style(account_key: str, style_key: str) -> dict | None:
    """
    Return the first Prompts_Master row matching exact account + style_key.
    Columns: style_key | account | label | description | t2i_base | niche_affinity | tags
    Returns None if not found or Sheets unavailable.
    """
    try:
        for row in get_prompts_master():
            if (str(row.get("account", "")).strip()    == account_key and
                    str(row.get("style_key", "")).strip() == style_key):
                return row
    except Exception:
        pass
    return None


def _get_prompt_for_style(account_key: str, style_key: str) -> str:
    """
    Fetch next rotating t2i_base prompt for account+style from Prompts_Master sheet.

    Sheet columns (EXACT match):
      style_key | account | label | description | t2i_base | niche_affinity | tags

    Multiple rows with same account+style_key → multiple prompt variants → sequential rotation.
    Fallback: hardcoded VISUAL_STYLES[style_key]['t2i_base'] if Sheets unavailable or no match.
    """
    hardcoded = VISUAL_STYLES.get(style_key, list(VISUAL_STYLES.values())[0]).get("t2i_base", "")

    try:
        all_rows = get_prompts_master()

        matching = [
            str(row.get("t2i_base", "")).strip()
            for row in all_rows
            if str(row.get("account", "")).strip()    == account_key
            and str(row.get("style_key", "")).strip() == style_key
            and str(row.get("t2i_base", "")).strip()
        ]

        if not matching:
            logger.warning(
                f"   [{account_key}] No Prompts_Master row for style='{style_key}' "
                f"— using hardcoded t2i_base"
            )
            return hardcoded

        tracker_key = f"{account_key}__{style_key}"
        tracker     = load_prompt_tracker()
        last_idx    = tracker.get(tracker_key, -1)
        next_idx    = (last_idx + 1) % len(matching)
        tracker[tracker_key] = next_idx
        save_prompt_tracker(tracker)

        chosen = matching[next_idx]
        logger.info(
            f"   [{account_key}] Prompt from Sheets [{next_idx+1}/{len(matching)}] "
            f"style='{style_key}' ({len(chosen)} chars)"
        )
        return chosen

    except Exception as e:
        logger.error(
            f"   [{account_key}] Prompts_Master FAILED — "
            f"{type(e).__name__}: {e} | using hardcoded t2i_base"
        )
        return hardcoded


def peek_next_pin_info() -> dict:
    """
    Public function — peek at the next pin for each account WITHOUT advancing trackers.
    Called by /api/next-pins dashboard endpoint.
    Returns style label, niche, prompt preview, source (Sheets/hardcoded), rotation position.
    """
    result = {}
    for acc_key in ["account_1", "account_2"]:
        next_style = _peek_current_style(acc_key)
        sheet_row  = _get_sheet_row_for_style(acc_key, next_style)
        style_meta = VISUAL_STYLES.get(next_style, {})

        if sheet_row:
            label       = str(sheet_row.get("label", "")).strip() or style_meta.get("label", next_style)
            niche       = str(sheet_row.get("niche_affinity", "")).strip()
            prompt_prev = (str(sheet_row.get("t2i_base", "")).strip()[:200] + "...") if sheet_row.get("t2i_base") else ""
            tags        = str(sheet_row.get("tags", "")).strip()
            source      = "Sheets"
        else:
            label       = style_meta.get("label", next_style)
            niche       = ", ".join(style_meta.get("niche_affinity", []))
            prompt_prev = style_meta.get("t2i_base", "")[:200] + "..."
            tags        = ", ".join(style_meta.get("tags", []))
            source      = "hardcoded"

        order   = _get_effective_style_order(acc_key)
        tracker = load_style_tracker()
        pos     = (tracker.get(acc_key, -1) + 1) % len(order)

        result[acc_key] = {
            "next_style":     next_style,
            "label":          label,
            "niche":          niche,
            "prompt_preview": prompt_prev,
            "tags":           tags,
            "source":         source,
            "rotation":       f"{pos + 1}/{len(order)}",
        }
    return result


# ══════════════════════════════════════════════════════════════════════════════
# 13 ELITE VISUAL STYLES — Sequential rotation coverage
# ══════════════════════════════════════════════════════════════════════════════
VISUAL_STYLES = {

    # ── 1. BOHO AESTHETIC STUDY ───────────────────────────────────────────────
    "boho_aesthetic_study": {
        "label":         "Boho Aesthetic Study",
        "description":   "A sun-drenched boho home study corner — cream walls covered in a gallery of pastel art prints, a worn wooden desk overflowing with paint brushes and ceramic mugs, trailing pothos vines cascading from floating shelves, warm rattan chair catching golden morning light",
        "t2i_base":      (
            "boho aesthetic home study corner, warm morning sunlight streaming through sheer white curtains, "
            "cream plaster walls covered in gallery wall of pastel abstract art prints in natural wood frames — "
            "sage green botanical, terracotta geometric, blush line-art prints, "
            "rustic light oak wooden desk with single drawer, "
            "colorful art supply jars and ceramic mugs holding paint brushes on desk surface, "
            "open art books and watercolor paper scattered casually on desk, "
            "rattan cane-back chair with brown leather seat in warm afternoon sun, "
            "floating wooden shelves above desk: stacked colorful books, small ceramic figurines, "
            "trailing pothos and golden devil's ivy hanging down from shelf edges, "
            "terracotta pot with small palm plant on desk corner, "
            "pink vintage-style desk lamp with brass neck casting warm 3000K pool of light, "
            "cream textured moroccan rug on light oak hardwood floor, "
            "soft dappled leaf shadow patterns on wall from window plant, "
            "shot on Canon EOS R5 35mm f/1.8 lens, warm 3400K color temperature, "
            "soft diffused window light, no harsh shadows, "
            "Kinfolk magazine lifestyle editorial, ultra-sharp foreground detail, creamy bokeh background, "
            "Pinterest viral home aesthetic photography"
        ),
        "niche_affinity": ["home", "cozy", "organize"],
        "seo_keywords":  ["boho home decor aesthetic", "aesthetic study room", "gallery wall ideas", "rattan furniture decor"],
        "tags":          ["BohoHomeAesthetic", "StudyRoomDecor", "GalleryWallInspo", "AestheticStudy", "HomeDecorGoals"],
    },

    # ── 2. SUNFLOWER YELLOW PORCH ─────────────────────────────────────────────
    "sunflower_yellow_porch": {
        "label":         "Sunflower Yellow Porch",
        "description":   "A cottage porch saturated in sunflower yellow — white wicker loveseat piled with yellow diamond-pattern cushions, sunflowers erupting from every pot and basket, yellow gingham rug underfoot, hanging planters of ivy tumbling from the roof rail",
        "t2i_base":      (
            "bright sunflower yellow aesthetic porch or sunroom interior, "
            "white ornate wicker loveseat and matching armchair with thick white cushions, "
            "yellow patterned throw pillows and diamond-knit cushions piled on wicker seating, "
            "large sunflower bouquets in yellow ceramic pots on floor and shelves, "
            "hanging yellow metal planters from ceiling chains with trailing green plants inside, "
            "yellow and white gingham checkered outdoor rug covering tile floor, "
            "white painted lattice fence railings with leafy green climbing vines, "
            "green tropical plants and potted herbs on every surface, "
            "white ceiling with ornate lantern pendant light fixture, "
            "bright summer daylight flooding in from open sides, mature green trees visible outside, "
            "warm vibrant 5500K daylight color temperature, clean white surfaces, "
            "shot on Sony A7R IV 35mm f/2.0 wide angle, "
            "bright airy high-key photography, vivid saturated colors, "
            "Southern Living magazine editorial aesthetic, summer sunshine mood"
        ),
        "niche_affinity": ["home", "cozy"],
        "seo_keywords":  ["sunflower porch decor", "yellow home decor aesthetic", "porch decorating ideas", "summer home decor"],
        "tags":          ["SunflowerDecor", "YellowAesthetic", "PorchDecorInspo", "SummerHome", "CottageVibes"],
    },

    # ── 3. PASTEL DREAMY KITCHEN ──────────────────────────────────────────────
    "pastel_dreamy_kitchen": {
        "label":         "Pastel Dreamy Kitchen",
        "description":   "A dreamy pastel kitchen — mint green lower cabinets, a ribbed mint ceramic pitcher overflowing with cherry blossom branches, a blush pink teapot on the wooden island, copper ring pendant lights above, strawberries in a white bowl",
        "t2i_base":      (
            "dreamy pastel aesthetic kitchen interior, "
            "mint green painted shaker-style lower kitchen cabinets with brass cup-pull hardware, "
            "light natural wood butcher-block island countertop, "
            "large ribbed mint green ceramic pitcher vase filled with masses of pink cherry blossom branches, "
            "small blush pink ceramic teapot with heart detail on island surface, "
            "mint green ceramic mug beside teapot, "
            "white ceramic bowl filled with fresh red strawberries on island left side, "
            "clear glass jar with oats beside bowl, "
            "abstract copper ring sculptural pendant light fixture above island, "
            "sage green painted walls with vertical wainscoting detail, "
            "framed pink floral watercolor art print on wall background, "
            "retro-style white coffee machine on countertop right side, "
            "warm morning light from unseen window, soft diffused 4000K balanced light, "
            "shot on Canon R6 50mm f/1.8, shallow depth of field on foreground props, "
            "soft pastel color grading, Elle Decor spring editorial style, "
            "bright airy kitchen lifestyle photography, ultra-sharp product textures"
        ),
        "niche_affinity": ["home", "kitchen"],
        "seo_keywords":  ["pastel kitchen decor", "aesthetic kitchen ideas", "mint green kitchen", "cute kitchen accessories"],
        "tags":          ["PastelKitchen", "DreamyKitchenDecor", "MintGreenAesthetic", "CottageKitchen", "AestheticHome"],
    },

    # ── 4. SAGE COPPER DINING ROOM ────────────────────────────────────────────
    "sage_copper_dining": {
        "label":         "Sage Copper Dining Room",
        "description":   "A magazine-worthy dining room with sage green walls, two sculptural copper dome pendant lights, a long natural oak dining table set with yellow linen napkins and bright daffodil centerpieces — mid-century velvet chairs in soft moss green",
        "t2i_base":      (
            "elegant sage green dining room interior, "
            "sage mint green painted walls with white crown molding and ceiling, "
            "two polished copper rose-gold dome pendant lights hanging from red cables, "
            "long natural light oak dining table with white linen table runner, "
            "place settings: yellow ceramic plates with yellow linen napkins, crystal wine glasses, "
            "large clear glass vase with abundant fresh yellow daffodil and narcissus bouquet centerpiece, "
            "secondary white ceramic vase with yellow blooms on sideboard, "
            "six mid-century modern velvet upholstered dining chairs in soft moss sage green, "
            "tapered solid oak chair legs, "
            "round organic-form gilt gold wall mirror on left wall, "
            "light oak sideboard credenza against left wall with decorative objects and lemons in bowl, "
            "large arched window with natural light flooding in from right side, "
            "green tropical palm plant in terracotta pot by window, "
            "vintage floral pattern area rug with warm yellow and red tones on white tile floor, "
            "warm bright afternoon light, 4500K color temperature, "
            "shot on Canon TS-E 24mm tilt-shift, perfect interior symmetry, "
            "Architectural Digest / House Beautiful editorial style, luxury interior photography"
        ),
        "niche_affinity": ["home", "kitchen"],
        "seo_keywords":  ["sage green dining room", "copper pendant light decor", "dining room aesthetic", "modern home decor ideas"],
        "tags":          ["SageGreenHome", "DiningRoomDecor", "CopperAesthetic", "ModernInterior", "HomeDecorInspo"],
    },

    # ── 5. VINTAGE WILDFLOWER DRIVE ───────────────────────────────────────────
    "vintage_wildflower_drive": {
        "label":         "Vintage Wildflower Drive",
        "description":   "A cream-yellow vintage Volkswagen Beetle parked in a vast wildflower meadow — thousands of pink cosmos flowers stretching to the horizon, snow-capped mountain peak glowing behind, golden afternoon light washing over the scene like a dream",
        "t2i_base":      (
            "cream pale yellow vintage Volkswagen Beetle classic car, 1970s model, "
            "parked at slight three-quarter front angle in the center of an open wildflower meadow, "
            "thousands of pink and white cosmos wildflowers in foreground and mid-ground, "
            "dried golden grass and tall wild herbs surrounding car at ground level, "
            "majestic snow-capped mountain peak centered behind car in the distance, "
            "pine forest tree line at mountain base, "
            "warm golden late-afternoon haze in sky, slight atmospheric glow, "
            "bokeh-soft wildflower foreground framing the vintage car, "
            "chrome bumper and round headlights catching golden sidelight, "
            "color palette: cream yellow car, pink flowers, gold grasses, white-blue mountain, "
            "warm cinematic color grade, Kodak Portra 400 film simulation, "
            "shot on Leica M11 50mm Summilux lens, medium depth of field, "
            "landscape meets automotive editorial photography, "
            "dreamy nostalgic romantic mood, film photography aesthetic"
        ),
        "niche_affinity": ["home", "cozy"],
        "seo_keywords":  ["vintage aesthetic photography", "cottagecore aesthetic", "wildflower field aesthetic", "retro travel vibes"],
        "tags":          ["VintageAesthetic", "WildflowerField", "RetroVibes", "DreamyPhotography", "CottageAesthetic"],
    },

    # ── 6. JUNGLE BIOPHILIC BEDROOM ───────────────────────────────────────────
    "jungle_biophilic_bedroom": {
        "label":         "Jungle Biophilic Bedroom",
        "description":   "A glass-house jungle bedroom where the outdoors lives inside — ceiling draped in cascading ivy vines, a low floor-level bed in soft mint green quilting, white floor-to-ceiling windows revealing towering green trees outside",
        "t2i_base":      (
            "biophilic jungle glass bedroom interior, "
            "white painted wooden ceiling and beams completely covered with cascading trailing ivy vines "
            "and heart-leaf philodendron in dense green canopy overhead, "
            "low floor-level platform bed without frame, sitting directly on natural jute area rug, "
            "soft mint sage green quilted comforter with white botanical print pillowcases, "
            "multiple white throw pillows and cushions arranged against headboard shelf, "
            "floor-to-ceiling white-frame windows on two walls, "
            "green leafy trees and outdoor nature visible through every window, "
            "bright natural diffused daylight flooding entire room, "
            "wooden window sill shelf lined with small terracotta herb pots, ceramic candles, wooden objects, "
            "woven rattan round floor pouf with open book beside bed, "
            "round braided natural jute rug under bed, "
            "small hanging macrame pendant lights with exposed Edison bulbs from ceiling, "
            "clean white walls, white painted wooden floors, "
            "5500K cool daylight white balance, ultra-bright airy exposure, "
            "shot on Sony A7R V 16mm ultra-wide, expansive room-capturing angle, "
            "Kinfolk meets House & Garden editorial, botanical bedroom lifestyle photography"
        ),
        "niche_affinity": ["home", "cozy"],
        "seo_keywords":  ["biophilic bedroom aesthetic", "jungle bedroom decor", "plant bedroom ideas", "boho bedroom aesthetic"],
        "tags":          ["JungleBedroom", "BiophilicDesign", "PlantAesthetic", "GreenBedroomDecor", "NatureHome"],
    },

    # ── 7. YELLOW KAWAII BEDROOM ──────────────────────────────────────────────
    "yellow_kawaii_bedroom": {
        "label":         "Yellow Kawaii Bedroom",
        "description":   "The coziest yellow bedroom — a floating platform bed glowing warm amber from LED underglow strips, white and yellow polka-dot comforter, floor-to-ceiling built-in wood wardrobes packed with plushie collections",
        "t2i_base":      (
            "kawaii cozy yellow aesthetic bedroom interior, "
            "floating platform bed with warm amber LED light strip beneath base glowing on white floor, "
            "white comforter with scattered yellow polka-dot pattern, yellow pillow shams, "
            "multiple soft plushie toys arranged on bed surface — white bunny, yellow chick, bear plushies, "
            "floor-to-ceiling built-in wardrobe system in warm natural light maple wood finish, "
            "upper wardrobe doors concealed, lower section open shelving displaying plushie collection, "
            "round happy sun-face wall-mounted mirror with cheerful expression above bed headboard, "
            "circular ring wall light fixture with warm glow on headboard wall, "
            "recessed ceiling spotlights with warm 3000K glow throughout room, "
            "LED cove strip lighting along ceiling cornice and wardrobe tops in warm amber, "
            "small yellow fresh flower bouquet on white bedside table, "
            "knitted round yellow pouffe ottoman at bed foot, "
            "sheer cream window curtains tied back with orange rope cord, "
            "entire room palette: warm maple wood, cream white, mustard yellow, amber glow, "
            "color temperature 3000K ultra-warm, rich cozy glow, "
            "shot on Canon EOS R6 24mm f/2.8, architectural interior angle, "
            "K-aesthetic bedroom photography, ultra-clean hyper-detailed room tour style"
        ),
        "niche_affinity": ["home", "cozy"],
        "seo_keywords":  ["kawaii bedroom decor", "yellow bedroom aesthetic", "cute bedroom ideas", "cozy room aesthetic"],
        "tags":          ["KawaiiBedroomDecor", "YellowBedroomAesthetic", "CozyRoomInspo", "CuteBedroom", "AestheticRoom"],
    },

    # ── 8. GOLDEN BALCONY GARDEN ──────────────────────────────────────────────
    "golden_balcony_garden": {
        "label":         "Golden Balcony Garden",
        "description":   "A tiny balcony transformed into a sun-drenched secret garden — white rattan corner sofa wrapped in yellow diamond-pattern cushions, sunflowers in wicker baskets, yellow and white gingham rug, cascading hanging ivy from above",
        "t2i_base":      (
            "cozy aesthetic apartment balcony garden, compact small balcony space, "
            "white rattan corner sofa with thick white and cream seat cushions filling the corner, "
            "multiple yellow and white patterned throw pillows and diamond-knit cushion covers on sofa, "
            "tall narrow wicker basket planter with bright yellow sunflower arrangement left of sofa, "
            "mixed yellow wildflowers and sunflowers in terracotta pots along balcony railing edge, "
            "yellow and white checked gingham rug covering entire balcony floor, "
            "cream canvas shade or voile curtain panel draping from ceiling corner for privacy, "
            "white wooden planks on balcony wall with hanging shelf of herb pots and botanical prints, "
            "hanging baskets of trailing ivy and string-of-pearls from ceiling overhang, "
            "dense mature green leafy trees visible beyond white railing, dappled sunlight, "
            "tall sunflower stems backlit by afternoon sun creating golden halo effect, "
            "stacked colorful books and yellow hat at sofa corner, "
            "warm 4000K natural balanced light, dappled leaf shadow patterns on wall and floor, "
            "shot on Canon EOS R5 35mm f/1.8, soft lifestyle editorial photography, "
            "warm golden summer color grade, Pinterest viral balcony aesthetic"
        ),
        "niche_affinity": ["home", "cozy"],
        "seo_keywords":  ["balcony garden aesthetic", "small balcony decor ideas", "outdoor decor aesthetic", "cozy balcony ideas"],
        "tags":          ["BalconyGarden", "OutdoorAesthetic", "CozyBalcony", "SunflowerVibes", "SmallSpaceDecor"],
    },

    # ── 9. KAWAII PASTEL GAMING SETUP ─────────────────────────────────────────
    "kawaii_pastel_gaming": {
        "label":         "Kawaii Pastel Gaming Setup",
        "description":   "A dreamy all-lavender gaming sanctuary — white PC case glowing soft purple, hexagonal wall panels in lilac, transparent pastel keyboard, dual monitors bathed in violet light, Sanrio figurines everywhere, cherry blossom string lights floating above",
        "t2i_base":      (
            "kawaii aesthetic gaming setup, full lavender purple monochrome color palette, "
            "white ATX PC case with tempered glass side panel, purple RGB fans glowing soft violet, "
            "hexagonal modular LED wall panels arranged above desk in honeycomb pattern glowing lilac, "
            "dual 27-inch monitors with galaxy space purple desktop wallpaper, "
            "transparent acrylic pastel purple mechanical keyboard, white wrist rest shaped like cloud, "
            "white wireless mouse on pastel purple large desk mat, "
            "small Sanrio kawaii figurines and star-shaped acrylic decor on desk corners, "
            "cherry blossom sakura string lights draped across top of setup, "
            "purple LED strip underglow beneath floating desk shelf, "
            "white floating shelves with pastel plushies and small succulents in pink pots, "
            "moon and star acrylic night light on desk side, "
            "room bathed in soft lavender ambient light, shadows purple-tinted, "
            "shot on Sony A7R V 35mm f/1.8, extreme shallow depth of field foreground bokeh, "
            "editorial gaming lifestyle photography, hyper-detailed product texture, "
            "dreamy pastel color grading, magazine-quality composition"
        ),
        "niche_affinity": ["tech", "gadgets"],
        "seo_keywords":  ["aesthetic gaming setup", "kawaii desk setup", "pastel room decor", "purple gaming setup accessories"],
        "tags":          ["KawaiiGamingSetup", "PastelAesthetic", "GamingRoom", "DeskSetupInspo", "PurpleAesthetic"],
    },

    # ── 10. COTTAGECORE TECH DEN ──────────────────────────────────────────────
    "cottagecore_tech_den": {
        "label":         "Cottagecore Tech Den",
        "description":   "A gamer's nature retreat — standing oak desk draped in trailing ivy vines, white mechanical keyboard with sage green keycaps, succulents and mushroom ceramics beside stacked fantasy novels",
        "t2i_base":      (
            "cottagecore gaming desk setup, light oak standing desk surface in sage green room, "
            "dual monitors — main showing Minecraft Java Edition lush biome, "
            "trailing artificial ivy and pothos vines cascading down walls around setup, "
            "white TKL mechanical keyboard with sage green and white keycaps, "
            "white wireless gaming mouse with cyan RGB underglow on cork coaster mousepad, "
            "small mushroom ceramic figurine and white pumpkin decoration on desk corner, "
            "three mini potted succulents in white ceramic pots along monitor shelf, "
            "hardcover fantasy novels stacked as monitor riser, spines facing outward, "
            "boom arm RGB microphone positioned left side, "
            "framed botanical print art on soft sage green wall, "
            "warm diffused afternoon window light, no harsh shadows, "
            "shot on Canon EOS R6 35mm f/1.4, editorial lifestyle gaming photography, "
            "natural color grading with warm greens and cream highlights, "
            "magazine-quality composition, depth of field pulling focus to keyboard"
        ),
        "niche_affinity": ["tech", "wfh", "gadgets"],
        "seo_keywords":  ["cottagecore desk setup", "aesthetic gaming setup", "nature desk accessories", "green gaming setup"],
        "tags":          ["CottageGaming", "AestheticSetup", "NatureDeskVibes", "GreenGamingSetup", "CozyTechDen"],
    },

    # ── 11. SAGE CLEAN WORKSPACE ──────────────────────────────────────────────
    "sage_clean_workspace": {
        "label":         "Sage Clean Workspace",
        "description":   "Hyper-curated sage green desk — iMac-style monitor, mint mechanical keyboard, tablet flat on oversized sage leather mat, fresh white daisies in a ribbed vase, yellow arc desk lamp",
        "t2i_base":      (
            "sage mint green aesthetic desk setup, large white desk surface flooded with natural window light, "
            "oversized sage green PU leather desk mat covering two-thirds of desk, "
            "mint blue-green all-in-one monitor displaying minimalist clock screensaver showing 10:10, "
            "sage green mechanical keyboard with mixed mint and white round keycaps centered on mat, "
            "matching pale green wireless mouse beside keyboard, "
            "white iPad tablet with white cable flat on left side of mat, "
            "AirPods Pro white case sitting beside keyboard, "
            "pink ribbed ceramic coffee mug at top right corner of mat, "
            "ribbed sage green ceramic vase with fresh white daisy stems on right side, "
            "small green cat ceramic figurine sitting on stacked pastel books, "
            "white retro-style mini coffee machine behind monitor, "
            "yellow arc clamp desk lamp pointing inward from right edge, "
            "white horizontal venetian blinds on window behind desk, green foliage visible outside, "
            "shot on Sony A7IV 50mm f/1.8, bright airy editorial photography, "
            "cool-warm color balance, 5500K daylight temperature, zero harsh shadows, "
            "Kinfolk meets K-aesthetic desk photography, ultra-sharp product detail"
        ),
        "niche_affinity": ["wfh", "tech", "gadgets"],
        "seo_keywords":  ["aesthetic desk setup", "work from home desk setup", "sage green desk accessories", "desk mat aesthetic"],
        "tags":          ["SageGreenDesk", "AestheticWorkspace", "CleanDeskSetup", "ProductivityAesthetic", "KAestheticDesk"],
    },

    # ── 12. WARM MINIMALIST BEDSIDE TECH ─────────────────────────────────────
    "warm_minimalist_bedside": {
        "label":         "Warm Minimalist Bedside Tech",
        "description":   "A silent bedroom corner at 9PM — one perfect gadget on a white nightstand, its warm amber glow casting the room in honey light, a ceramic mug beside a reed diffuser, wooden panel walls, crisp linen",
        "t2i_base":      (
            "minimalist smart bedside table setup, clean white floating nightstand, "
            "white LED digital alarm clock with wireless phone charging pad base, clock displaying 21:32 PM, "
            "warm amber light bleeding softly beneath clock device onto white table surface, "
            "small black reed diffuser with amber glass bottle on right side of table, "
            "simple cream-white ceramic mug on left side, "
            "light ash wood panel wall behind nightstand, warm timber grain visible, "
            "soft linen pillow and white duvet edge visible at bottom right, "
            "sheer cream curtain panel behind to left, backlit by soft outdoor glow, "
            "room in deep shadow, only bedside amber light as sole light source, "
            "color temperature 2400K ultra-warm, rich contrast between glow and shadow, "
            "shot on Canon EOS R5 85mm f/1.4, cinematic low-light photography, "
            "extreme shallow depth of field, clock face sharp, surroundings softly bokeh, "
            "premium lifestyle product photography, Wallpaper magazine aesthetic"
        ),
        "niche_affinity": ["tech", "smarthome", "gadgets"],
        "seo_keywords":  ["smart home gadgets aesthetic", "minimalist bedroom tech", "wireless charger aesthetic", "cozy bedroom setup"],
        "tags":          ["MinimalistBedroom", "SmartHomeTech", "BedsideSetup", "CleanRoomAesthetic", "GadgetLifestyle"],
    },

    # ── 13. YELLOW CREATOR FLAT LAY (NEW) ────────────────────────────────────
    "yellow_creator_flatlay": {
        "label":         "Yellow Creator Flat Lay",
        "description":   "The ultimate creator aesthetic flat lay — a silver MacBook with yellow over-ear headphones resting on the keyboard, a mustard yellow mirrorless camera in the corner, fresh yellow roses scattered across white linen, warm golden light pouring over everything from the side",
        "t2i_base":      (
            "aesthetic creator lifestyle flat lay, overhead bird's eye view shot on white linen fabric surface, "
            "silver MacBook Pro laptop open at slight angle, screen showing colorful editorial content, "
            "mustard yellow over-ear headphones with chrome accents resting on laptop keyboard center, "
            "compact mustard yellow mirrorless DSLR camera with prime lens sitting top-right corner of frame, "
            "three fresh yellow roses with green stems placed diagonally across lower-left of frame, "
            "one yellow rose bloom close to camera, one near laptop touchpad, one near bottom-left corner, "
            "small white gypsophila baby's breath flowers scattered between roses, "
            "a few scattered popcorn kernels for casual texture detail, "
            "warm golden afternoon sidelight from upper right, creating soft warm shadow to left, "
            "color palette: silver-grey laptop, mustard yellow headphones and camera, yellow roses, white linen, "
            "warm 3600K golden color temperature, soft gentle shadows, "
            "shot on Sony A7R V 35mm f/1.8, strict overhead flat lay angle, "
            "ultra-sharp product detail, lifestyle creator editorial photography, "
            "warm golden color grade, Vsco film aesthetic, Instagram editorial flat lay"
        ),
        "niche_affinity": ["tech", "wfh", "gadgets"],
        "seo_keywords":  ["aesthetic flat lay photography", "creator setup aesthetic", "yellow aesthetic desk", "laptop aesthetic photography"],
        "tags":          ["CreatorAesthetic", "YellowFlatLay", "LaptopAesthetic", "ContentCreatorVibes", "AestheticSetup"],
    },

    # ── 14. YELLOW FLORAL CARAVAN COTTAGE ────────────────────────────────────
    "yellow_floral_caravan": {
        "label":         "Yellow Floral Caravan Cottage",
        "description":   "A whimsical sunshine yellow caravan-style tiny home on wheels — an oval arch entrance frames a cozy interior with a white wicker loveseat, cascading yellow chrysanthemums and purple blooms overflowing every ledge, vintage wagon wheels at the base, fairy lights strung above a wooden deck",
        "t2i_base":      (
            "whimsical yellow cottage caravan tiny home exterior, "
            "sunshine lemon yellow painted wooden curved barrel-roof structure on wheels, "
            "large white oval arch entrance framing cozy interior — white wicker loveseat with yellow cushions inside, "
            "cascading masses of bright yellow chrysanthemums and marigolds overflowing window boxes and deck railings, "
            "lavender purple blooms in ceramic pots flanking entrance arch, "
            "hanging wicker basket planters with trailing greenery from arch ceiling, "
            "vintage decorative wagon wheels painted cream-white at base of structure, "
            "oval porthole-style windows with white trim on side wall covered in climbing roses, "
            "natural wood plank deck surrounding the structure with potted topiary balls, "
            "string fairy lights hanging above deck from tree to caravan roof, "
            "dense green leafy trees and garden backdrop, soft dappled natural light, "
            "rocking chair and small yellow decorative elements on deck, "
            "color palette: sunshine yellow, white, lavender purple, moss green, natural wood, "
            "warm afternoon dappled sunlight, 4200K balanced light temperature, "
            "shot on Canon EOS R5 35mm f/2.0, wide environmental lifestyle editorial, "
            "dreamy cottagecore fairytale garden photography, Pinterest tiny home aesthetic"
        ),
        "niche_affinity": ["home", "cozy"],
        "seo_keywords":  ["tiny home aesthetic", "cottagecore house exterior", "yellow cottage decor", "whimsical garden home"],
        "tags":          ["TinyHomeAesthetic", "CottageVibes", "YellowCottage", "WhimsicalHome", "FairytaleCottage"],
    },

    # ── 15. MINT COTTAGE GARDEN EXTERIOR ─────────────────────────────────────
    "mint_cottage_garden": {
        "label":         "Mint Cottage Garden Exterior",
        "description":   "A storybook mint green cottage framed in blooming white hydrangeas — arched entry door with warm golden window light glowing from within, a winding stepping stone path of oversized white oval stones through manicured green lawn, white pergola draped in blossoming white trees on the left",
        "t2i_base":      (
            "mint sage green painted cottage house exterior, "
            "pastel mint green stucco walls with white trim molding and window frames, "
            "steep white gable roof with pale yellow painted wooden shingles, "
            "arched front entry door glowing warm amber-yellow from interior light, "
            "large arched transom window above door with warm golden curtains behind glass, "
            "rectangular sash windows on left and right facade with warm yellow drapes inside, "
            "white pergola canopy structure attached to left side, draped in flowering white cherry blossom branches, "
            "bright white hydrangea bushes in full bloom flanking front path both sides, "
            "winding front garden path of large round white oval stepping stones, "
            "lush mowed vivid green lawn surrounding path, scattered white flower petals, "
            "terracotta pots with green plants on front porch steps, "
            "white picket fence in background right side, pale blue clear sky above, "
            "natural wooden garden bench with white metal frame on left near pergola, "
            "color palette: mint green, bright white, golden window glow, vivid green lawn, "
            "bright even midday light, 5500K clear daylight, soft clean shadows, "
            "shot on Sony A7R V 24mm f/2.8, architectural exterior lifestyle photography, "
            "dreamy soft pastel color grading, House Beautiful spring editorial style"
        ),
        "niche_affinity": ["home", "cozy"],
        "seo_keywords":  ["cottage house exterior ideas", "mint green house aesthetic", "garden home decor", "dream home exterior"],
        "tags":          ["CottageExterior", "MintGreenHome", "DreamHomeGoals", "GardenCottage", "HouseExteriorInspo"],
    },

    # ── 16. LANTERN FAIRYTALE TREEHOUSE ──────────────────────────────────────
    "lantern_fairytale_treehouse": {
        "label":         "Lantern Fairytale Treehouse",
        "description":   "A magical cluster of tiny glowing white cottages nestled at the base of an enormous ancient tree — warm lanterns hanging from every branch like fireflies frozen in time, peach and cream polka-dot foliage overhead, the whole scene reflected in still twilight water below",
        "t2i_base":      (
            "magical fairytale miniature village cottages nestled at base of giant ancient tree, waterside at dusk, "
            "cluster of small white stucco cottage buildings stacked on rocky island shore — arched windows glowing warm amber from inside, "
            "worn stone steps and cobblestone path connecting cottages at different levels, "
            "multiple black iron lanterns hanging from tree branches at varying heights on thin chains, each glowing warm 2700K amber inside, "
            "enormous ancient gnarled tree trunk with massive overhanging canopy above entire scene, "
            "tree foliage rendered as soft rounded polka-dot circles in pastel peach, cream, teal, and rust orange tones, "
            "warm bokeh light orbs floating throughout the image — out-of-focus lanterns and firefly glow, "
            "still glassy water in foreground reflecting warm amber treehouse glow and pastel sky, "
            "soft pastel dusk sky: peach horizon blending to powder blue above, "
            "flowering vines and orange blooms climbing cottage walls, "
            "ornate street lamp post glowing near cottage entrance stairs, "
            "color palette: warm amber glow, cream white, peach orange, soft teal, muted rust, "
            "twilight golden hour, 2500K warm candlelight atmosphere, rich deep shadows, "
            "shot on Canon EOS R5 85mm f/1.4, extreme compression telephoto, "
            "dreamy storybook illustration meets photorealistic photography, fantasy editorial style"
        ),
        "niche_affinity": ["home", "cozy"],
        "seo_keywords":  ["fairytale cottage aesthetic", "magical home aesthetic", "treehouse decor inspiration", "enchanted home vibes"],
        "tags":          ["FairytaleHome", "MagicalCottage", "DreamyAesthetic", "EnchantedVibes", "CottageAesthetic"],
    },
}

# ══════════════════════════════════════════════════════════════════════════════
# NICHE → VISUAL STYLE mapping
# ══════════════════════════════════════════════════════════════════════════════
NICHE_STYLE_MAP = {
    "home":      ["boho_aesthetic_study", "sunflower_yellow_porch", "sage_copper_dining", "golden_balcony_garden"],
    "kitchen":   ["pastel_dreamy_kitchen", "sage_copper_dining", "boho_aesthetic_study"],
    "cozy":      ["boho_aesthetic_study", "golden_balcony_garden", "jungle_biophilic_bedroom", "yellow_kawaii_bedroom"],
    "gadgets":   ["kawaii_pastel_gaming", "warm_minimalist_bedside", "yellow_creator_flatlay"],
    "organize":  ["sage_clean_workspace", "boho_aesthetic_study"],
    "tech":      ["kawaii_pastel_gaming", "sage_clean_workspace", "yellow_creator_flatlay"],
    "budget":    ["sage_clean_workspace", "warm_minimalist_bedside"],
    "phone":     ["warm_minimalist_bedside", "kawaii_pastel_gaming"],
    "smarthome": ["warm_minimalist_bedside", "yellow_kawaii_bedroom"],
    "wfh":       ["sage_clean_workspace", "cottagecore_tech_den", "yellow_creator_flatlay"],
}

# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPTS
# ══════════════════════════════════════════════════════════════════════════════
_SYSTEM_PROMPT = """\
You are a dual expert: a world-class AI Art Director and a viral Pinterest copywriter.
Your ONLY output is a single valid JSON object — 100% VIRAL_PIN aesthetic content.

VISUAL DIRECTION PHILOSOPHY:
- Think like a Vogue Living / Architectural Digest / Kinfolk photographer.
- Every image prompt must specify: exact lighting setup, camera lens, color temperature, mood, texture details, compositional technique.
- Prompts must be so specific that an AI image generator produces a magazine-cover-worthy image on first try.
- No generic words like "beautiful" or "nice" — use precise art direction language.
- For home decor account: target BRIGHT, COLORFUL, WARM, CHEERFUL aesthetics — NOT dark or moody.

COPYWRITING PHILOSOPHY:
- Titles must be emotionally charged discovery moments — not descriptions.
- Descriptions must trigger a sensory or aspirational feeling — smell, texture, warmth, desire.
- Zero product names, zero prices, zero CTAs, zero affiliate signals. Pure lifestyle emotion.

ABSOLUTE RULES:
1. Output ONLY a single valid JSON object. Zero prose, zero explanation.
2. pin_type MUST always be exactly: "VIRAL_PIN"
3. visual_prompt = comma-separated T2I keywords with art direction specifics. No sentences. No brands.
4. visual_prompt MUST end with: 4K ultra HD, photorealistic, highly detailed, award-winning photography
5. Tags: CamelCase, no hashtag symbol, exactly 5 tags.
6. You MUST use EXACTLY the visual_style key specified in the prompt — do NOT change it.
"""

_GEMINI_SYSTEM_INSTRUCTION = """\
You are an Elite Visual Art Director and viral Pinterest content strategist.
Your sole job: craft one world-class VIRAL_PIN for the EXACT visual style specified.

STRICT RULES:
- Output ONLY raw JSON. No markdown. No explanation. No text before or after JSON.
- pin_type MUST always be exactly: "VIRAL_PIN"
- visual_style MUST be exactly the key provided in the prompt — never change it.
- visual_prompt = comma-separated T2I art-direction keywords. Specify: lighting, lens, camera angle, color temperature, texture, mood, compositional technique. No brand names. No sentences.
- visual_prompt MUST end with: 4K ultra HD, photorealistic, highly detailed, award-winning photography
- title = emotionally charged curiosity hook. NOT a description. Max 90 chars.
- description = 2-3 sentences of sensory lifestyle copy. No products, no prices, no CTAs.
- Tags: CamelCase, no #, exactly 5 tags.
- alt_text = Highly descriptive, SEO-optimized alternative text for the image. Max 200 chars.
- For HOME DECOR account: ALWAYS BRIGHT, COLORFUL, WARM — NEVER dark or moody.
"""

# ══════════════════════════════════════════════════════════════════════════════
# ACCOUNT PROFILES
# ══════════════════════════════════════════════════════════════════════════════
_ACCOUNT_PROFILES = {
    "account_1": (
        "ACCOUNT: HomeDecor & Lifestyle (account_1)\n"
        "Audience: Homemakers, interior design aspirants, nesting millennials and Gen Z — 18-45, female-skewed, USA/UK/India\n"
        "VISUAL MANDATE: BRIGHT, COLORFUL, WARM, CHEERFUL — think Pinterest's most-saved home pins: sunlight, pastels, plants, cozy warmth, golden light, cheerful yellow and mint and sage tones.\n"
        "Tone: Sensory, intimate, aspirational — like a stylish friend sharing a room that stopped her mid-scroll\n"
        "Copy Voice: 'This corner of the world exists and you deserve to live in it'\n"
        "Goal: Maximum saves via pure aesthetic visual desire — every pin should make someone want to recreate it NOW"
    ),
    "account_2": (
        "ACCOUNT: Tech & WFH Aesthetic (account_2)\n"
        "Audience: Tech enthusiasts, remote workers, content creators, setup culture followers — 18-35, USA/India\n"
        "Preferred Visual Styles: kawaii_pastel_gaming, cottagecore_tech_den, sage_clean_workspace, warm_minimalist_bedside, yellow_creator_flatlay\n"
        "Tone: Sharp, curated, aspirational — the feeling of a setup so intentional it stops you mid-scroll\n"
        "Copy Voice: 'The setup that makes every session feel like building something that matters'\n"
        "Goal: Maximum saves via aspirational workspace and tech aesthetic"
    ),
}

# ══════════════════════════════════════════════════════════════════════════════
# HARDCODED FALLBACKS
# ══════════════════════════════════════════════════════════════════════════════
HARDCODED_FALLBACK: dict = {
    "account_1": {
        "pin_type":      "VIRAL_PIN",
        "strategy":      "Boho Aesthetic Study Fallback",
        "visual_style":  "boho_aesthetic_study",
        "niche":         "cozy",  # ← NICHE FOR BOARD SELECTION
        "vibe":          "Golden morning light, rattan chair, gallery wall, trailing pothos, art supplies on oak desk",
        "title":         "This Study Corner Made Me Want To Stay Home Forever",
        "description":   (
            "Warm light pools through sheer curtains and lands on a mess of paint brushes you'll never want to clean up. "
            "The gallery wall tells stories; the trailing pothos reaches toward the window like it knows something you don't. "
            "This is what home should feel like every single morning."
        ),
        "tags":          ["BohoHomeAesthetic", "StudyRoomDecor", "GalleryWallInspo", "AestheticStudy", "HomeDecorGoals"],
        "alt_text":      "A highly aesthetic and visually pleasing Pinterest setup matching the exact vibe of the image.",
        "visual_prompt": (
            "boho aesthetic home study corner, warm morning golden sunlight through sheer white curtains, "
            "cream plaster walls with pastel abstract art prints gallery wall in natural wood frames, "
            "rustic light oak wooden desk with paint brushes in ceramic jars, rattan cane-back chair, "
            "trailing pothos vine from floating shelf, terracotta plant pots, pink brass desk lamp, "
            "cream moroccan rug, light oak hardwood floor, warm 3400K color temperature, "
            "Canon EOS R5 35mm f/1.8, shallow depth of field, Kinfolk editorial style, "
            "4K ultra HD, photorealistic, highly detailed, award-winning photography"
        ),
        "ratio": "9:16",
    },
    "account_2": {
        "pin_type":      "VIRAL_PIN",
        "strategy":      "Yellow Creator Flat Lay Fallback",
        "visual_style":  "yellow_creator_flatlay",
        "niche":         "wfh",  # ← NICHE FOR BOARD SELECTION
        "vibe":          "Yellow headphones on MacBook, mustard camera, yellow roses, white linen, golden sidelight",
        "title":         "This Is What a Creative Morning Actually Looks Like",
        "description":   (
            "Mustard yellow against cool silver — the headphones rest exactly where inspiration left them. "
            "Roses because why not. Camera because always. "
            "The kind of morning desk that makes you excited to open your laptop."
        ),
        "tags":          ["CreatorAesthetic", "YellowFlatLay", "LaptopAesthetic", "ContentCreatorVibes", "AestheticSetup"],
        "alt_text":      "A highly aesthetic and visually pleasing Pinterest setup matching the exact vibe of the image.",
        "visual_prompt": (
            "aesthetic creator lifestyle flat lay, overhead bird's eye view, white linen fabric surface, "
            "silver MacBook Pro open showing colorful content, mustard yellow over-ear headphones on keyboard center, "
            "mustard yellow mirrorless DSLR camera top-right corner, "
            "fresh yellow roses with green stems scattered across frame, white gypsophila flowers, "
            "warm golden afternoon sidelight from upper right, soft warm shadows, "
            "color palette: silver laptop, mustard yellow, yellow roses, white linen, "
            "Sony A7R V 35mm f/1.8, strict overhead flat lay angle, ultra-sharp product detail, "
            "warm golden color grade, VSCO film aesthetic, "
            "4K ultra HD, photorealistic, highly detailed, award-winning photography"
        ),
        "ratio": "9:16",
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# PROMPT BUILDER — Forces specific style (rotation engine controls which one)
# ══════════════════════════════════════════════════════════════════════════════
def _build_forced_style_prompt(profile: str, forced_style_key: str, ratio: str, t2i_prompt: str = None,
                               sheet_row: dict = None) -> str:
    """
    Build the LLM prompt for a specific style.

    Content priority (Sheet = source of truth):
    ─────────────────────────────────────────────────────────────────────
    1. sheet_row (Prompts_Master)  ← PRIMARY — label, description, t2i_base, tags, niche all from here
    2. VISUAL_STYLES[key]          ← EMERGENCY ONLY — if Sheets completely down
    3. bare minimum defaults       ← last resort so pipeline never crashes
    ─────────────────────────────────────────────────────────────────────

    t2i_prompt: already-resolved t2i_base string (from _get_prompt_for_style with rotation)
    sheet_row:  full Prompts_Master row dict — used for label, description, tags
    """
    ratio_cfg = _RATIOS[ratio]

    # ── Resolve content: Sheet row > VISUAL_STYLES > bare minimum ─────────────
    if sheet_row:
        # PRIMARY: everything from Sheet row
        label       = str(sheet_row.get("label",       "")).strip() or forced_style_key.replace("_", " ").title()
        description = str(sheet_row.get("description", "")).strip() or "A beautiful aesthetic lifestyle scene."
        t2i_base    = t2i_prompt or str(sheet_row.get("t2i_base", "")).strip()
        raw_tags    = str(sheet_row.get("tags", "")).strip()
        tags        = [t.strip() for t in raw_tags.split(",") if t.strip()][:5]
        if not tags:
            tags    = ["AestheticVibes", "HomeDecor", "PinterestInspired", "CozyHome", "LifestyleGoals"]
        source_log  = "Sheet"

    elif VISUAL_STYLES.get(forced_style_key):
        # EMERGENCY FALLBACK: Sheets down, use hardcoded VISUAL_STYLES
        sd          = VISUAL_STYLES[forced_style_key]
        label       = sd["label"]
        description = sd["description"]
        t2i_base    = t2i_prompt or sd["t2i_base"]
        tags        = sd["tags"]
        source_log  = "VISUAL_STYLES (emergency)"

    else:
        # LAST RESORT: style not in Sheet and not hardcoded — bare minimum
        label       = forced_style_key.replace("_", " ").title()
        description = "A beautiful aesthetic lifestyle scene, warm light, cozy atmosphere."
        t2i_base    = t2i_prompt or "aesthetic lifestyle photography, warm natural light, highly detailed"
        tags        = ["AestheticVibes", "HomeDecor", "PinterestInspired", "CozyHome", "LifestyleGoals"]
        source_log  = "bare-minimum"
        logger.warning(f"[{forced_style_key}] No Sheet row and not in VISUAL_STYLES — using bare minimum")

    logger.info(f"   [{forced_style_key}] Prompt content source: {source_log}")



    return f"""TASK: Generate ONE VIRAL_PIN for the EXACT visual style specified below. Do NOT change the style.

ACCOUNT PROFILE
{profile}

VISUAL STYLE (use this EXACTLY — do not change or substitute)
Style Key:   {forced_style_key}
Label:       {label}
Description: {description}
T2I Base:    {t2i_base}

PIN SPECIFICATIONS
Image ratio: {ratio_cfg['label']} ({ratio_cfg['w']}x{ratio_cfg['h']}px)
Pin type: VIRAL_PIN — 100% editorial aesthetic AI-generated image. Zero products. Zero text in image.

CREATIVE DIRECTION
1. STYLE KEY: "{forced_style_key}" — non-negotiable. Use the Label + Description + T2I Base above exactly.

2. VISUAL ART DIRECTION (most important field — "visual_prompt")
   - Expand the T2I Base into a hyper-specific art-direction prompt.
   - Specify: dominant light source + color temperature, camera lens, compositional technique,
     key textures, mood/atmosphere in one phrase.
   - Every detail must push toward editorial magazine quality.
   - MUST end with: 4K ultra HD, photorealistic, highly detailed, award-winning photography

3. COPYWRITING — ELITE TIER
   - Title: An emotional discovery moment. NOT a description. "Would I stop scrolling for this?"
     Examples:
       "This Room Made Me Forget I Had Anywhere To Be"
       "I Didn't Know A Morning Could Look Like This"
       "This Setup Is Making Me Rethink Everything"
   - Description: 2-3 sentences. Pure sensory and emotional pull.
     Mention one specific texture, one specific light quality, one specific feeling.
     Never describe the image. Make the reader FEEL the image.

4. TAGS: CamelCase, no hashtag symbol, exactly 5, SEO-optimized for Pinterest discoverability.
   Base tags to use/remix: {json.dumps(tags)}

5. ALT TEXT: Highly descriptive SEO-optimized text describing the image visually. Max 200 chars.

OUTPUT FORMAT (JSON only — no other text before or after)
{{
  "pin_type": "VIRAL_PIN",
  "strategy": "<brief name for this specific creative direction>",
  "visual_style": "{forced_style_key}",
  "vibe": "<1-line art direction mood summary, max 80 chars>",
  "title": "<emotionally charged curiosity hook, max 90 chars>",
  "description": "<sensory lifestyle copy, 2-3 sentences, zero products/CTAs/prices, max 380 chars>",
  "tags": ["<Tag1>", "<Tag2>", "<Tag3>", "<Tag4>", "<Tag5>"],
  "alt_text": "<Descriptive SEO-optimized alt text describing the image visually, max 200 chars>",
  "visual_prompt": "<ultra-specific T2I art-direction prompt expanded from T2I Base, ends with: 4K ultra HD, photorealistic, highly detailed, award-winning photography>",
  "ratio": "{ratio}"
}}"""


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _extract_json(raw: str) -> dict:
    cleaned  = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    start    = cleaned.find("{")
    end      = cleaned.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found. Raw: {cleaned[:200]}")
    json_str = cleaned[start:end]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON parse failed: {e}. Extracted: {json_str[:300]}")


def _validate(result: dict, account_key: str) -> None:
    required = ("pin_type", "strategy", "vibe", "title", "description", "tags", "alt_text", "visual_prompt")
    for field in required:
        if field not in result:
            raise KeyError(f"Missing '{field}' in CMO response for {account_key}.")
    if result.get("pin_type") != "VIRAL_PIN":
        raise ValueError(f"CMO returned non-VIRAL_PIN for {account_key} — forcing override.")
    # Enforce alt_text max 200 chars (Pinterest SEO limit — 500+ causes errors)
    if len(result.get("alt_text", "")) > 200:
        result["alt_text"] = result["alt_text"][:197] + "..."
    vp = result.get("visual_prompt", "")
    if "photorealistic" not in vp or "4K" not in vp:
        result["visual_prompt"] = vp.rstrip(", ") + ", 4K ultra HD, photorealistic, highly detailed, award-winning photography"


def _build_from_style_data(forced_style: str, ratio: str, niche: str, account_key: str = "",
                           sheet_row: dict = None) -> dict:
    """
    Build a complete VIRAL_PIN strategy WITHOUT any LLM call.
    Used when ALL LLM calls fail (non-429 errors).

    Content priority (Sheet = source of truth):
    ─────────────────────────────────────────────────────────────────────
    1. sheet_row (Prompts_Master)  ← PRIMARY — label, description, t2i_base, tags from here
    2. VISUAL_STYLES[key]          ← EMERGENCY — Sheets down
    3. first VISUAL_STYLES entry   ← last resort, pipeline never crashes
    ─────────────────────────────────────────────────────────────────────
    Rotation tracker still advances normally — only LLM copy generation is skipped.
    """
    # ── Resolve content: Sheet row > VISUAL_STYLES > last resort ──────────────
    if sheet_row:
        label       = str(sheet_row.get("label",       "")).strip() or forced_style.replace("_", " ").title()
        desc        = str(sheet_row.get("description", "")).strip() or "A beautiful aesthetic lifestyle scene."
        raw_tags    = str(sheet_row.get("tags",        "")).strip()
        tags        = [t.strip() for t in raw_tags.split(",") if t.strip()][:5]
        if not tags:
            tags    = ["AestheticVibes", "HomeDecor", "PinterestInspired", "CozyHome", "LifestyleGoals"]
        source_log  = "Sheet"
    elif VISUAL_STYLES.get(forced_style):
        sd          = VISUAL_STYLES[forced_style]
        label       = sd["label"]
        desc        = sd["description"]
        tags        = sd["tags"]
        source_log  = "VISUAL_STYLES (emergency)"
    else:
        sd          = list(VISUAL_STYLES.values())[0]
        label       = forced_style.replace("_", " ").title()
        desc        = sd["description"]
        tags        = sd["tags"]
        source_log  = "last-resort"

    # ── t2i / visual_prompt: Sheet rotation > sheet_row t2i_base > VISUAL_STYLES ──
    if account_key:
        visual_prompt = _get_prompt_for_style(account_key, forced_style).strip().rstrip(", ")
    elif sheet_row:
        visual_prompt = str(sheet_row.get("t2i_base", "")).strip().rstrip(", ")
    else:
        visual_prompt = VISUAL_STYLES.get(forced_style, list(VISUAL_STYLES.values())[0])["t2i_base"].strip().rstrip(", ")

    if "4K ultra HD" not in visual_prompt:
        visual_prompt += ", 4K ultra HD, photorealistic, highly detailed, award-winning photography"

    # Title variants — rotated by style key hash for variety
    title_hooks = [
        f"This {label} Is The Most Saved Aesthetic Right Now",
        f"I Didn't Know A Room Could Look Like This",
        f"This {label} Made Me Stop Scrolling Completely",
        f"The {label} Aesthetic That's Taking Over Pinterest",
        f"This Corner Changed How I Think About Home",
    ]
    title       = title_hooks[hash(forced_style) % len(title_hooks)][:90]
    description = desc[:380]
    alt_text    = f"Aesthetic {label} — Pinterest viral lifestyle photography, ultra-detailed"[:200]

    logger.info(
        f"   [{forced_style}] No-LLM direct build | source={source_log} | "
        f"t2i={len(visual_prompt)} chars | tags={tags}"
    )
    return {
        "pin_type":      "VIRAL_PIN",
        "strategy":      f"Sheet Direct (no LLM) — {label}",
        "visual_style":  forced_style,
        "niche":         niche,
        "vibe":          desc[:80],
        "title":         title,
        "description":   description,
        "tags":          tags,
        "alt_text":      alt_text,
        "visual_prompt": visual_prompt,
        "ratio":         ratio,
    }


# ══════════════════════════════════════════════════════════════════════════════
# LLM CALLS
# ══════════════════════════════════════════════════════════════════════════════
def _call_gemini_sync(prompt: str) -> str:
    if not _gemini_client:
        raise ValueError("GEMINI_API_KEY not configured.")
    response = _gemini_client.models.generate_content(
        model=GEMINI_CMO_MODEL,
        contents=prompt,
        config=_gtypes.GenerateContentConfig(
            system_instruction=_GEMINI_SYSTEM_INSTRUCTION,
            temperature=0.80,
            max_output_tokens=6000,
            response_mime_type="application/json",
        ),
    )
    return response.text.strip()


def _call_cerebras_sync(prompt: str) -> str:
    if not _cerebras_client:
        raise ValueError("CEREBRAS_API_KEY not configured.")
    try:
        response = _cerebras_client.chat.completions.create(
            model=CEREBRAS_CMO_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.80,
            max_tokens=6000,
        )
        return response.choices[0].message.content
    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "rate" in err_str.lower():
            raise RuntimeError(f"Cerebras rate-limited (429) — aborting: {e}") from e
        raise


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATION — Sequential rotation per account
# ══════════════════════════════════════════════════════════════════════════════
def _call_cmo_for_account(account_key: str, metrics: dict) -> dict:
    """
    Gets the NEXT style in rotation, calls LLM for copy + prompt expansion.

    DATA FLOW (Sheet = single source of truth):
    ─────────────────────────────────────────────────────────────────────
    1. style_key   → just an identifier (e.g. "cherry_blossom_fairy_lights_nook")
    2. sheet_row   → full content row from Prompts_Master:
                     label | description | t2i_base | niche_affinity | tags
    3. LLM         → receives sheet_row content, generates:
                     title | description copy | alt_text | expanded visual_prompt | tags
    4. Image gen   → uses visual_prompt from LLM (expanded from t2i_base)
    5. Board select→ uses niche from sheet_row.niche_affinity

    VISUAL_STYLES dict = emergency fallback ONLY (when Sheets is completely down).
    It is NOT the source of truth for any style.

    ERROR HANDLING HIERARCHY:
    1. Gemini fails  (any reason) → log EXACT error → try Cerebras
    2. Cerebras 429               → raise RuntimeError → node uses HARDCODED_FALLBACK
    3. Cerebras fails (non-429)   → _build_from_style_data() with sheet_row (zero LLM)
    ─────────────────────────────────────────────────────────────────────
    """
    ratio        = _pick_ratio()
    profile      = _ACCOUNT_PROFILES[account_key]
    forced_style = _get_next_style(account_key)   # ← STYLE ROTATION ENGINE

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 1: Fetch full content row from Prompts_Master Sheet
    # sheet_row IS the content — label, description, t2i_base, niche, tags all from here.
    # VISUAL_STYLES is only checked if Sheet is completely unavailable.
    # ══════════════════════════════════════════════════════════════════════════
    sheet_row = _get_sheet_row_for_style(account_key, forced_style)

    # ── Niche: always from sheet_row first ────────────────────────────────────
    if sheet_row:
        raw_niche  = str(sheet_row.get("niche_affinity", "")).strip()
        niche_list = [n.strip() for n in raw_niche.split(",") if n.strip()]
        if not niche_list:
            # niche_affinity column empty → fallback to VISUAL_STYLES if exists
            niche_list = VISUAL_STYLES.get(forced_style, {}).get("niche_affinity", ["default"])
    else:
        # Sheet unavailable → try VISUAL_STYLES emergency fallback
        niche_list = VISUAL_STYLES.get(forced_style, {}).get("niche_affinity", ["default"])

    niche = random.choice(niche_list) if niche_list else "default"

    # ── t2i_base prompt: Sheet rotation (multiple variants) → hardcoded fallback ──
    # _get_prompt_for_style handles its own rotation tracker per style
    sheet_prompt = _get_prompt_for_style(account_key, forced_style)

    logger.info(f"   [{account_key}] Generating: {forced_style} | niche={niche} | ratio={ratio} | sheet_row={'YES' if sheet_row else 'NO (using hardcoded)'}")

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 2: Build LLM prompt — feeds full sheet_row content to LLM
    # LLM task: write viral copy (title, description, alt_text) + expand visual_prompt
    # ══════════════════════════════════════════════════════════════════════════
    prompt = _build_forced_style_prompt(profile, forced_style, ratio, sheet_prompt, sheet_row=sheet_row)

    # ── PRIMARY: Gemini ───────────────────────────────────────────────────────
    try:
        logger.info(f"   [{account_key}] Gemini (primary)...")
        raw    = _call_gemini_sync(prompt)
        result = _extract_json(raw)
        _validate(result, account_key)
        result["pin_type"]     = "VIRAL_PIN"
        result["visual_style"] = forced_style
        result["ratio"]        = result.get("ratio", ratio)
        result["niche"]        = niche
        logger.info(f"   [{account_key}] Gemini OK | style={forced_style} | niche={niche}")
        return result
    except Exception as gemini_err:
        logger.error(
            f"   [{account_key}] GEMINI FAILED — "
            f"{type(gemini_err).__name__}: {gemini_err}"
        )

    # ── FALLBACK: Cerebras ────────────────────────────────────────────────────
    try:
        logger.info(f"   [{account_key}] Cerebras fallback...")
        raw    = _call_cerebras_sync(prompt)
        result = _extract_json(raw)
        _validate(result, account_key)
        result["pin_type"]     = "VIRAL_PIN"
        result["visual_style"] = forced_style
        result["ratio"]        = result.get("ratio", ratio)
        result["niche"]        = niche
        logger.info(f"   [{account_key}] Cerebras OK | style={forced_style} | niche={niche}")
        return result
    except RuntimeError as rate_err:
        # 429 — nothing we can do, raise so node uses HARDCODED_FALLBACK
        logger.error(
            f"   [{account_key}] CEREBRAS 429 RATE LIMIT — "
            f"{type(rate_err).__name__}: {rate_err} | "
            f"→ Using HARDCODED_FALLBACK (rate limited)"
        )
        raise
    except Exception as cerebras_err:
        # Non-429 error — zero LLM, build directly from sheet_row content
        logger.error(
            f"   [{account_key}] CEREBRAS FAILED — "
            f"{type(cerebras_err).__name__}: {cerebras_err} | "
            f"→ Building directly from sheet_row for: {forced_style}"
        )
        return _build_from_style_data(forced_style, ratio, niche, account_key, sheet_row=sheet_row)


# ══════════════════════════════════════════════════════════════════════════════
# LANGGRAPH NODE
# ══════════════════════════════════════════════════════════════════════════════
async def node_cmo_mastermind(state: MastermindState) -> dict:
    """
    Node 2 — CMO Mastermind [Elite Visual v6 — Sequential Rotation]
    
    ROTATION: Each run picks the NEXT style in the ordered queue.
    A1: 8 styles cycle → Run1=boho_study, Run2=sunflower_porch, Run3=pastel_kitchen...
    A2: 5 styles cycle → Run1=kawaii_gaming, Run2=cottagecore_den, Run3=sage_workspace...
    
    Tracker: data/style_tracker.json
    """
    trigger = state.get("cycle_trigger", "")

    only_a1 = "account1" in trigger and "account2" not in trigger
    only_a2 = "account2" in trigger and "account1" not in trigger
    run_a1  = not only_a2
    run_a2  = not only_a1

    label = "A1 only" if only_a1 else ("A2 only" if only_a2 else "Both")
    logger.info(f"[Node 2 - CMO] Sequential Rotation v6 | {label} | trigger={trigger}")

    # Log what's coming up next (peek without advancing)
    if run_a1:
        logger.info(f"   A1 next style: {_peek_current_style('account_1')}")
    if run_a2:
        logger.info(f"   A2 next style: {_peek_current_style('account_2')}")

    a1_metrics = state.get("a1_raw_analytics", [])
    a2_metrics = state.get("a2_raw_analytics", [])
    fallback   = False

    # ── Account 1 (HomeDecor)
    if run_a1:
        try:
            a1_strategy = await asyncio.to_thread(_call_cmo_for_account, "account_1", a1_metrics)
            strategy_src = "VISUAL_STYLES-direct" if "VISUAL_STYLES Direct" in a1_strategy.get("strategy", "") else "LLM"
            logger.info(
                f"[Node 2] A1 OK ({strategy_src}) | "
                f"style={a1_strategy.get('visual_style','?')} | "
                f"ratio={a1_strategy.get('ratio','9:16')}"
            )
        except RuntimeError as rate_err:
            # Only RuntimeError (429) reaches here — non-429 is handled inside _call_cmo_for_account
            logger.error(
                f"[Node 2] A1 HARDCODED FALLBACK — REASON: {type(rate_err).__name__}: {rate_err}"
            )
            a1_strategy = HARDCODED_FALLBACK["account_1"]
            fallback = True
        except Exception as e:
            logger.error(
                f"[Node 2] A1 HARDCODED FALLBACK — REASON: {type(e).__name__}: {e}"
            )
            a1_strategy = HARDCODED_FALLBACK["account_1"]
            fallback = True
    else:
        a1_strategy = {}

    # ── Account 2 (Tech / WFH)
    if run_a2:
        try:
            a2_strategy = await asyncio.to_thread(_call_cmo_for_account, "account_2", a2_metrics)
            strategy_src = "VISUAL_STYLES-direct" if "VISUAL_STYLES Direct" in a2_strategy.get("strategy", "") else "LLM"
            logger.info(
                f"[Node 2] A2 OK ({strategy_src}) | "
                f"style={a2_strategy.get('visual_style','?')} | "
                f"ratio={a2_strategy.get('ratio','9:16')}"
            )
        except RuntimeError as rate_err:
            logger.error(
                f"[Node 2] A2 HARDCODED FALLBACK — REASON: {type(rate_err).__name__}: {rate_err}"
            )
            a2_strategy = HARDCODED_FALLBACK["account_2"]
            fallback = True
        except Exception as e:
            logger.error(
                f"[Node 2] A2 HARDCODED FALLBACK — REASON: {type(e).__name__}: {e}"
            )
            a2_strategy = HARDCODED_FALLBACK["account_2"]
            fallback = True
    else:
        a2_strategy = {}

    return {
        "a1_cmo_strategy":    a1_strategy,
        "a2_cmo_strategy":    a2_strategy,
        "fallback_triggered": fallback,
    }
