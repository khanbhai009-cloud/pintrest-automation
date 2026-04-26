"""
mastermind/node_cmo.py — Node 2: CMO Mastermind  [ELITE VISUAL UPGRADE v5 — BRIGHT AESTHETIC]

STRATEGY : 100% VIRAL_PIN — ultra-realistic, editorial-grade aesthetic AI images only.
PRIMARY  : Gemini 2.5 Flash  (JSON mode forced via response_mime_type)
FALLBACK : Cerebras qwen-3-235b  (429 = no retry, skip to hardcoded immediately)
HARDCODED: Last-resort static strategy keeps pipeline alive

CMO reads analytics -> picks best performing Visual Style from 12 options -> outputs VIRAL_PIN.
Visual Styles (12):
  HOME DECOR ACCOUNT (account_1) — bright, colorful, modern Pinterest-viral aesthetic:
  1. Boho Aesthetic Study        — warm plants, gallery wall, rattan, golden morning light, art prints
  2. Sunflower Yellow Porch      — white wicker, sunflowers, yellow checkered rug, hanging baskets
  3. Pastel Dreamy Kitchen       — mint green + pink, cherry blossoms, copper pendant, strawberries
  4. Sage Copper Dining Room     — sage walls, copper dome lights, yellow daffodils, mid-century chairs
  5. Vintage Wildflower Drive    — yellow VW Beetle, pink wildflower field, snow mountain backdrop
  6. Jungle Biophilic Bedroom    — ceiling vines, floor-level bed, mint comforter, glass walls, daylight
  7. Yellow Kawaii Bedroom       — LED underglow bed, plushies, warm wood built-ins, cozy golden glow
  8. Golden Balcony Garden       — cozy wicker sofa, yellow sunflowers, checkered rug, dappled sunlight

  TECH ACCOUNT (account_2) — Pinterest-viral aesthetic, NOT cyberpunk:
  9.  Kawaii Pastel Gaming Setup   — lavender hex panels, transparent keyboard, Sanrio, sakura lights
  10. Cottagecore Tech Den         — ivy walls, Minecraft desk, sage keycaps, mushroom ceramics, fantasy books
  11. Sage Clean Workspace         — mint iMac, green keyboard, daisy vase, yellow lamp, K-aesthetic flat lay
  12. Warm Minimalist Bedside Tech — white nightstand, smart clock+charger, amber glow, reed diffuser, wood panels

Ratio per pin: randomly chosen — 9:16 portrait OR 1:1 square (70/30 split)
"""
import asyncio
import json
import logging
import random
import re

from config import CEREBRAS_API_KEY, CEREBRAS_CMO_MODEL, GEMINI_API_KEY, GEMINI_CMO_MODEL
from mastermind.state import MastermindState

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
# 12 ELITE VISUAL STYLES — Analytics-driven CMO selection
# Each style has: label, description, t2i_base (ultra-detailed), niche_affinity,
# seo_keywords (from KEYWORDS_BY_NICHE), tags
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
        "description":   "A dreamy pastel kitchen that feels like it belongs in a fairy tale — mint green lower cabinets, a ribbed mint ceramic pitcher overflowing with cherry blossom branches, a blush pink teapot on the wooden island, copper ring pendant lights above, strawberries in a white bowl",
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
        "description":   "A magazine-worthy dining room with sage green walls, two sculptural copper dome pendant lights, a long natural oak dining table set with yellow linen napkins and bright daffodil centerpieces — mid-century velvet chairs in soft moss green, golden rug underfoot",
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
        "description":   "A glass-house jungle bedroom where the outdoors lives inside — ceiling draped in cascading ivy vines and heart-leaf philodendron, a low floor-level bed in soft mint green quilting, white floor-to-ceiling windows revealing towering green trees outside, woven rattan pouf on the jute rug",
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
        "description":   "The coziest yellow bedroom you've ever seen — a floating platform bed glowing warm amber from LED underglow strips, white and yellow polka-dot comforter, floor-to-ceiling built-in wood wardrobes with open shelves packed with plushie collections, happy sun-face round wall mirror",
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
            "glimpse of wardrobe hanging area with all-white clothing, "
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
        "description":   "A tiny balcony transformed into a sun-drenched secret garden — white rattan corner sofa wrapped in yellow diamond-pattern cushions, sunflowers in wicker baskets, yellow and white gingham rug, cascading hanging ivy from above, golden summer trees swaying beyond the railing",
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
        "description":   "A gamer's nature retreat — standing oak desk draped in trailing ivy vines, white mechanical keyboard with sage green keycaps glowing cyan, succulents and mushroom ceramics beside stacked fantasy novels, boom-arm mic, the feeling of logging into a forest",
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
        "description":   "Hyper-curated sage green desk — iMac-style monitor, mint mechanical keyboard with mixed green keycaps, tablet flat on oversized sage leather mat, fresh white daisies in a ribbed vase, yellow arc desk lamp — K-aesthetic productivity at its most irresistible",
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
        "description":   "A silent bedroom corner at 9PM — one perfect gadget on a white nightstand, its warm amber glow beneath a digital clock casting the room in honey light, a ceramic mug beside a reed diffuser, wooden panel walls, crisp linen — luxury simplicity at its most aspirational",
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
}

# ══════════════════════════════════════════════════════════════════════════════
# NICHE → VISUAL STYLE mapping (for analytics-informed routing)
# ══════════════════════════════════════════════════════════════════════════════
NICHE_STYLE_MAP = {
    "home":      ["boho_aesthetic_study", "sunflower_yellow_porch", "sage_copper_dining", "golden_balcony_garden"],
    "kitchen":   ["pastel_dreamy_kitchen", "sage_copper_dining", "boho_aesthetic_study"],
    "cozy":      ["boho_aesthetic_study", "golden_balcony_garden", "jungle_biophilic_bedroom", "yellow_kawaii_bedroom"],
    "gadgets":   ["kawaii_pastel_gaming", "warm_minimalist_bedside"],
    "organize":  ["sage_clean_workspace", "boho_aesthetic_study"],
    "tech":      ["kawaii_pastel_gaming", "sage_clean_workspace"],
    "budget":    ["sage_clean_workspace", "warm_minimalist_bedside"],
    "phone":     ["warm_minimalist_bedside", "kawaii_pastel_gaming"],
    "smarthome": ["warm_minimalist_bedside", "yellow_kawaii_bedroom"],
    "wfh":       ["sage_clean_workspace", "cottagecore_tech_den"],
}

# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPTS — Elite Visual Art Director + Marketing Copywriter
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
  Think: sunlight, pastels, plants, golden glow, cheerful colors, cozy warmth.

COPYWRITING PHILOSOPHY:
- Write like a lifestyle editor who makes readers stop scrolling and stare.
- Titles must be emotionally charged discovery moments — not descriptions.
- Descriptions must trigger a sensory or aspirational feeling — smell, texture, warmth, desire.
- Zero product names, zero prices, zero CTAs, zero affiliate signals. Pure lifestyle emotion.

ABSOLUTE RULES (any violation = system failure):
1. Output ONLY a single valid JSON object. Zero prose, zero explanation.
2. pin_type MUST always be exactly: "VIRAL_PIN"
3. visual_prompt = comma-separated T2I keywords with art direction specifics. No sentences. No brands.
4. visual_prompt MUST end with: 4K ultra HD, photorealistic, highly detailed, award-winning photography
5. Tags: CamelCase, no hashtag symbol, exactly 5 tags.
"""

_GEMINI_SYSTEM_INSTRUCTION = """\
You are an Elite Visual Art Director and viral Pinterest content strategist.
Your sole job: analyze analytics → pick the best-performing Visual Style → craft one world-class VIRAL_PIN.

STRICT RULES:
- Output ONLY raw JSON. No markdown. No explanation. No text before or after JSON.
- pin_type MUST always be exactly: "VIRAL_PIN"
- visual_prompt = comma-separated T2I art-direction keywords. Specify: lighting, lens, camera angle, color temperature, texture, mood, compositional technique. No brand names. No sentences.
- visual_prompt MUST end with: 4K ultra HD, photorealistic, highly detailed, award-winning photography
- title = emotionally charged curiosity hook. NOT a description. Max 90 chars.
- description = 2-3 sentences of sensory lifestyle copy. No products, no prices, no CTAs.
- Tags: CamelCase, no #, exactly 5 tags.
- For HOME DECOR account (account_1): always generate BRIGHT, COLORFUL, WARM visuals — sunshine, pastels, plants, golden tones. Never dark, moody, or noir.
"""

# ══════════════════════════════════════════════════════════════════════════════
# ACCOUNT PROFILES — Audience-specific art direction personas
# ══════════════════════════════════════════════════════════════════════════════
_ACCOUNT_PROFILES = {
    "account_1": (
        "ACCOUNT: HomeDecor & Lifestyle (account_1)\n"
        "Audience: Homemakers, interior design aspirants, nesting millennials and Gen Z — 18-45, female-skewed, USA/UK/India\n"
        "Preferred Visual Styles: boho_aesthetic_study, sunflower_yellow_porch, pastel_dreamy_kitchen, sage_copper_dining, vintage_wildflower_drive, jungle_biophilic_bedroom, yellow_kawaii_bedroom, golden_balcony_garden\n"
        "VISUAL MANDATE: BRIGHT, COLORFUL, WARM, CHEERFUL — think Pinterest's most-saved home pins: sunlight, pastels, plants, cozy warmth, golden light, cheerful yellow and mint and sage tones.\n"
        "Tone: Sensory, intimate, aspirational — like a stylish friend sharing a room that stopped her mid-scroll\n"
        "Copy Voice: 'This corner of the world exists and you deserve to live in it'\n"
        "Goal: Maximum saves via pure aesthetic visual desire — every pin should make someone want to recreate it NOW"
    ),
    "account_2": (
        "ACCOUNT: Tech & WFH Aesthetic (account_2)\n"
        "Audience: Tech enthusiasts, remote workers, setup culture followers — 18-35, male-skewed, USA/India\n"
        "Preferred Visual Styles: kawaii_pastel_gaming, cottagecore_tech_den, sage_clean_workspace, warm_minimalist_bedside\n"
        "Tone: Sharp, curated, aspirational — the feeling of a setup so intentional it stops you mid-scroll\n"
        "Copy Voice: 'The desk setup that makes every work session feel like building something that matters'\n"
        "Goal: Maximum saves via aspirational workspace and tech aesthetic — viewers want to build what they see"
    ),
}

# ══════════════════════════════════════════════════════════════════════════════
# HARDCODED FALLBACKS — Guaranteed VIRAL_PIN if all LLMs fail
# ══════════════════════════════════════════════════════════════════════════════
HARDCODED_FALLBACK: dict = {
    "account_1": {
        "pin_type":      "VIRAL_PIN",
        "strategy":      "Boho Aesthetic Study Fallback",
        "visual_style":  "boho_aesthetic_study",
        "vibe":          "Golden morning light, rattan chair, gallery wall, trailing pothos, art supplies on oak desk",
        "title":         "This Study Corner Made Me Want To Stay Home Forever",
        "description":   (
            "Warm light pools through sheer curtains and lands on a mess of paint brushes you'll never want to clean up. "
            "The gallery wall tells stories; the trailing pothos reaches toward the window like it knows something you don't. "
            "This is what home should feel like every single morning."
        ),
        "tags":          ["BohoHomeAesthetic", "StudyRoomDecor", "GalleryWallInspo", "AestheticStudy", "HomeDecorGoals"],
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
        "strategy":      "Kawaii Pastel Gaming Fallback",
        "visual_style":  "kawaii_pastel_gaming",
        "vibe":          "Lavender hex panels, white glowing PC, transparent keyboard, Sanrio figurines, sakura lights",
        "title":         "This Setup Made Me Realize My Desk Could Be a Dream",
        "description":   (
            "Soft violet light falls over every surface — the hexagonal panels pulse gently, "
            "the keyboard glows through its own translucency like a window to another dimension. "
            "This isn't just a gaming setup. It's proof that your space can feel exactly like how you want your life to feel."
        ),
        "tags":          ["KawaiiGamingSetup", "PastelAesthetic", "GamingRoom", "DeskSetupInspo", "PurpleAesthetic"],
        "visual_prompt": (
            "kawaii aesthetic gaming setup, full lavender purple monochrome color palette, "
            "white ATX PC case tempered glass side panel purple RGB fans glowing soft violet, "
            "hexagonal modular LED wall panels honeycomb pattern glowing lilac above desk, "
            "dual 27-inch monitors galaxy space purple desktop wallpaper, "
            "transparent acrylic pastel purple mechanical keyboard white cloud wrist rest, "
            "white wireless mouse on pastel purple large desk mat, "
            "Sanrio kawaii figurines star-shaped acrylic decor desk corners, "
            "cherry blossom sakura string lights draped above setup, "
            "purple LED strip underglow beneath floating shelf, "
            "shot Sony A7R V 35mm f/1.8, extreme shallow depth of field foreground bokeh, "
            "editorial gaming lifestyle photography, dreamy pastel color grading, "
            "4K ultra HD, photorealistic, highly detailed, award-winning photography"
        ),
        "ratio": "9:16",
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# PROMPT BUILDER — Full art-direction brief for the CMO LLM
# ══════════════════════════════════════════════════════════════════════════════
def _build_viral_prompt(profile: str, metrics_str: str, ratio: str) -> str:
    ratio_cfg  = _RATIOS[ratio]
    styles_str = json.dumps(
        {k: {
            "label":         v["label"],
            "description":   v["description"],
            "t2i_base":      v["t2i_base"],
            "niche_affinity": v["niche_affinity"],
        }
         for k, v in VISUAL_STYLES.items()},
        indent=2
    )
    return f"""TASK: Generate ONE VIRAL_PIN strategy. Analyze analytics → select the best Visual Style → craft a world-class aesthetic pin.

ACCOUNT PROFILE
{profile}

PERFORMANCE ANALYTICS (last 30 days)
{metrics_str}

12 VISUAL STYLES (pick the one matching analytics momentum + account audience)
{styles_str}

PIN SPECIFICATIONS
Image ratio: {ratio_cfg['label']} ({ratio_cfg['w']}x{ratio_cfg['h']}px)
Pin type: VIRAL_PIN — 100% editorial aesthetic AI-generated image. Zero products. Zero text in image.

CREATIVE DIRECTION
1. STYLE SELECTION
   - Study analytics profile (High-Impression / Low-Engagement → bolder visual hook needed).
   - Pick the Visual Style with momentum OR best fitting account audience preference.
   - If stagnant analytics: pick a DIFFERENT style than the default fallback to force fresh content.
   - For account_1 (Home Decor): ALWAYS pick from home decor styles (1-8). ALWAYS use BRIGHT, WARM, COLORFUL visuals.

2. VISUAL ART DIRECTION (this is the most important field)
   - Expand t2i_base into a hyper-specific art-direction prompt.
   - Specify ALL of: dominant light source + color temperature (e.g., "warm 3200K backlight"), 
     camera lens (e.g., "Canon 35mm f/1.8"), compositional technique (e.g., "rule of thirds, foreground bokeh"),
     key textures (e.g., "rough linen, brushed brass, matte ceramic"),
     mood/atmosphere in one phrase (e.g., "intimate Sunday morning stillness").
   - Every detail must push toward editorial magazine quality.
   - MUST end with: 4K ultra HD, photorealistic, highly detailed, award-winning photography

3. COPYWRITING — ELITE TIER
   - Title: An emotional discovery moment. NOT a description. Ask yourself: "Would I stop scrolling for this?"
     Examples of ELITE titles: 
       "This Room Made Me Forget I Had Anywhere To Be"
       "The Corner That Made Me Realize Home Should Feel Like This"
       "I Didn't Know A Kitchen Could Make Mornings Feel This Good"
   - Description: 2-3 sentences. Pure sensory and emotional pull. 
     Mention one specific texture, one specific light quality, one specific feeling.
     Never describe the image. Make the reader FEEL the image.

4. TAGS: CamelCase, no hashtag, exactly 5, SEO-optimized for Pinterest discoverability.

OUTPUT FORMAT (JSON only — no other text before or after)
{{
  "pin_type": "VIRAL_PIN",
  "strategy": "<brief name for this specific creative direction>",
  "visual_style": "<exact key from the 12 styles above>",
  "vibe": "<1-line art direction mood summary, max 80 chars>",
  "title": "<emotionally charged curiosity hook, max 90 chars>",
  "description": "<sensory lifestyle copy, 2-3 sentences, zero products/CTAs/prices, max 380 chars>",
  "tags": ["<Tag1>", "<Tag2>", "<Tag3>", "<Tag4>", "<Tag5>"],
  "visual_prompt": "<ultra-specific T2I art-direction prompt expanded from t2i_base, ends with: 4K ultra HD, photorealistic, highly detailed, award-winning photography>",
  "ratio": "{ratio}"
}}"""


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _choose_pin_type() -> str:
    """Always VIRAL_PIN — 100% visual strategy, no affiliate routing."""
    return "VIRAL_PIN"


def _extract_json(raw: str) -> dict:
    """Robustly extract JSON from model output — handles fences, leading text, whitespace."""
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
    required = ("pin_type", "strategy", "vibe", "title", "description", "tags", "visual_prompt")
    for field in required:
        if field not in result:
            raise KeyError(f"Missing '{field}' in CMO response for {account_key}.")
    if result.get("pin_type") != "VIRAL_PIN":
        raise ValueError(f"CMO returned non-VIRAL_PIN for {account_key} — forcing override.")
    # Enforce visual_prompt ending
    vp = result.get("visual_prompt", "")
    if "photorealistic" not in vp or "4K" not in vp:
        result["visual_prompt"] = vp.rstrip(", ") + ", 4K ultra HD, photorealistic, highly detailed, award-winning photography"


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
            temperature=0.80,       # slightly higher for bolder creative choices
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
# MAIN ORCHESTRATION — Per-account CMO strategy generation
# ══════════════════════════════════════════════════════════════════════════════
def _call_cmo_for_account(account_key: str, metrics: dict, pin_type_override: str = None) -> dict:
    # pin_type_override ignored — 100% VIRAL_PIN always
    ratio       = _pick_ratio()
    profile     = _ACCOUNT_PROFILES[account_key]
    metrics_str = json.dumps(metrics, indent=2)

    logger.info(f"   [{account_key}] pin=VIRAL_PIN | ratio={ratio}")
    prompt = _build_viral_prompt(profile, metrics_str, ratio)

    # PRIMARY: Gemini
    try:
        logger.info(f"   [{account_key}] Gemini (primary)...")
        raw    = _call_gemini_sync(prompt)
        result = _extract_json(raw)
        _validate(result, account_key)
        result["pin_type"] = "VIRAL_PIN"
        result["ratio"]    = result.get("ratio", ratio)
        logger.info(f"   [{account_key}] Gemini OK | style={result.get('visual_style', '?')}")
        return result
    except Exception as gemini_err:
        logger.warning(f"   [{account_key}] Gemini failed: {gemini_err}")

    # FALLBACK: Cerebras (skip if 429)
    try:
        logger.info(f"   [{account_key}] Cerebras fallback...")
        raw    = _call_cerebras_sync(prompt)
        result = _extract_json(raw)
        _validate(result, account_key)
        result["pin_type"] = "VIRAL_PIN"
        result["ratio"]    = result.get("ratio", ratio)
        logger.info(f"   [{account_key}] Cerebras OK | style={result.get('visual_style', '?')}")
        return result
    except RuntimeError as rate_err:
        logger.warning(f"   [{account_key}] {rate_err}")
        raise
    except Exception as cerebras_err:
        logger.warning(f"   [{account_key}] Cerebras failed: {cerebras_err}")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# METRICS HELPER — Translates Google Sheets rows into analytics profile dict
# ══════════════════════════════════════════════════════════════════════════════
def _compute_metrics(rows: list) -> dict:
    is_stagnant = not rows or rows[0].get("Date") == "fallback"
    if is_stagnant:
        return {
            "impressions_avg": 0, "clicks_avg": 0,
            "outbound_avg": 0,    "saves_avg":  0,
            "profile": "Stagnant — pivot to bold new visual style",
        }

    def _avg(key: str) -> float:
        vals = []
        for r in rows:
            raw = r.get(key, 0)
            try:
                vals.append(float(str(raw).replace(",", "") or 0))
            except (ValueError, TypeError):
                vals.append(0.0)
        return round(sum(vals) / len(vals), 1) if vals else 0.0

    imp      = _avg("Impressions")
    clicks   = _avg("Clicks")
    saves    = _avg("Saves")
    outbound = _avg("Outbound Clicks")

    if imp > 5000 and clicks < 100 and saves < 100:
        profile = "High-Impression / Low-Engagement — sharpen visual hook, stronger emotional title"
    elif clicks > 200 or saves > 200:
        profile = "High-Engagement / Conversion-Ready — double down on current aesthetic style"
    else:
        profile = "Stagnant — pivot to a different visual style for fresh momentum"

    return {
        "impressions_avg": imp,
        "clicks_avg":      clicks,
        "outbound_avg":    outbound,
        "saves_avg":       saves,
        "profile":         profile,
    }


# ══════════════════════════════════════════════════════════════════════════════
# LANGGRAPH NODE
# ══════════════════════════════════════════════════════════════════════════════
async def node_cmo_mastermind(state: MastermindState) -> dict:
    """
    Node 2 — CMO Mastermind [Elite Visual v5 — Bright Aesthetic]
    Always VIRAL_PIN. 12 visual styles. Ultra-realistic T2I prompts. Elite copy.
    Primary: Gemini | Fallback: Cerebras | Last resort: hardcoded strategy
    """
    trigger = state.get("cycle_trigger", "")

    only_a1 = "account1" in trigger and "account2" not in trigger
    only_a2 = "account2" in trigger and "account1" not in trigger
    run_a1  = not only_a2
    run_a2  = not only_a1

    label = "A1 only" if only_a1 else ("A2 only" if only_a2 else "Both")
    logger.info(f"[Node 2 - CMO] VIRAL_PIN Elite Visual v5 | {label} | trigger={trigger}")

    a1_metrics = _compute_metrics(state["a1_raw_analytics"])
    a2_metrics = _compute_metrics(state["a2_raw_analytics"])
    fallback   = False

    # ── Account 1 (HomeDecor)
    if run_a1:
        logger.info(f"   A1 analytics: {a1_metrics['profile']}")
        try:
            a1_strategy = await asyncio.to_thread(_call_cmo_for_account, "account_1", a1_metrics)
            logger.info(f"[Node 2] A1 → VIRAL_PIN | style={a1_strategy.get('visual_style','?')} | ratio={a1_strategy.get('ratio','9:16')}")
        except Exception as e:
            logger.error(f"[Node 2] All CMO models failed for A1: {e}. Using hardcoded fallback.")
            a1_strategy = HARDCODED_FALLBACK["account_1"]
            fallback = True
    else:
        a1_strategy = {}

    # ── Account 2 (Tech / WFH)
    if run_a2:
        logger.info(f"   A2 analytics: {a2_metrics['profile']}")
        try:
            a2_strategy = await asyncio.to_thread(_call_cmo_for_account, "account_2", a2_metrics)
            logger.info(f"[Node 2] A2 → VIRAL_PIN | style={a2_strategy.get('visual_style','?')} | ratio={a2_strategy.get('ratio','9:16')}")
        except Exception as e:
            logger.error(f"[Node 2] All CMO models failed for A2: {e}. Using hardcoded fallback.")
            a2_strategy = HARDCODED_FALLBACK["account_2"]
            fallback = True
    else:
        a2_strategy = {}

    return {
        "a1_cmo_strategy":    a1_strategy,
        "a2_cmo_strategy":    a2_strategy,
        "fallback_triggered": fallback,
    }
