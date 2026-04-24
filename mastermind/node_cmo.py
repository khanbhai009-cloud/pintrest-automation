"""
mastermind/node_cmo.py — Node 2: CMO Mastermind  [ELITE VISUAL UPGRADE v4]

STRATEGY : 100% VIRAL_PIN — ultra-realistic, editorial-grade aesthetic AI images only.
PRIMARY  : Gemini 2.5 Flash  (JSON mode forced via response_mime_type)
FALLBACK : Cerebras qwen-3-235b  (429 = no retry, skip to hardcoded immediately)
HARDCODED: Last-resort static strategy keeps pipeline alive

CMO reads analytics -> picks best performing Visual Style from 12 options -> outputs VIRAL_PIN.
Visual Styles (12):
  HOME DECOR ACCOUNT (account_1):
  1. Biophilic Luxury Interior     — plants + editorial lighting + premium materials
  2. Moody Cinematic Sunset        — golden-hour landscapes, glass reflections, silhouettes
  3. Hygge Cozy Architecture       — candlelight, stone, plush, intimate warmth
  4. Cottagecore Fairy Dream       — fairytale cottage, lanterns, enchanted garden
  5. Neon Mirror Vanity            — gold mirror, fairy lights, red florals, candles
  6. Celestial LED Art             — LED tree branches, white light sculpture, wall art
  7. Vibrant Monochrome Interior   — saturated single-hue living rooms, luxury chandelier
  8. Cinematic Retro Scenes        — vintage car, rose cottage, film grain nostalgia

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
# 10 ELITE VISUAL STYLES — Analytics-driven CMO selection
# Each style has: label, description, t2i_base (ultra-detailed), niche_affinity,
# seo_keywords (from KEYWORDS_BY_NICHE), tags
# ══════════════════════════════════════════════════════════════════════════════
VISUAL_STYLES = {

    # ── 1. BIOPHILIC LUXURY INTERIOR ──────────────────────────────────────────
    "biophilic_luxury": {
        "label":         "Biophilic Luxury Interior",
        "description":   "Lush tropical indoor plants, arched floor-to-ceiling windows, warm afternoon sun casting dramatic leaf shadows on cream plaster walls, rattan furniture, terracotta accents, brushed-gold fixtures — Scandinavian meets Bali resort",
        "t2i_base":      (
            "biophilic luxury interior, towering monstera deliciosa, fiddle leaf fig, trailing pothos wall, "
            "arched floor-to-ceiling windows, cream plaster walls, afternoon golden sunlight streaming in, "
            "dramatic leaf shadow patterns on wall, rattan accent chair, terracotta ceramic pots, "
            "brushed-gold hardware, linen curtains billowing gently, warm 3200K ambient light, "
            "editorial interior photography, shot on Canon EOS R5 35mm f/1.8, "
            "shallow depth of field, ultra-sharp foreground details, dreamy background bokeh, "
            "magazine-worthy composition, Architectural Digest style"
        ),
        "niche_affinity": ["home", "cozy", "organize"],
        "seo_keywords":  ["aesthetic room decor", "indoor plants aesthetic", "nordic home decor", "minimalist home accessories"],
        "tags":          ["BiophilicDesign", "LuxuryInterior", "IndoorPlantAesthetic", "HomeDecorInspo", "NaturalLiving"],
    },

    # ── 2. MOODY CINEMATIC SUNSET ─────────────────────────────────────────────
    "moody_cinematic_sunset": {
        "label":         "Moody Cinematic Sunset",
        "description":   "Golden hour over still water, dramatic cumulus clouds ablaze in amber and rose, Spanish moss draped oak framing the sky, mirror-perfect lake reflection doubling the color spectacle",
        "t2i_base":      (
            "cinematic golden hour landscape, perfectly still lake mirror reflection, "
            "dramatic cumulus clouds backlit in amber rose orange, Spanish moss hanging from ancient live oak, "
            "lush green foreground vegetation, color temperature 3800K warm, "
            "volumetric light rays piercing through clouds, subtle lens flare, "
            "long exposure photography effect, ultra-wide 16mm cinematic lens, "
            "Magnum Photos documentary style, extreme dynamic range, "
            "rich saturation, deep shadows, luminous highlights, "
            "photojournalism meets fine art landscape"
        ),
        "niche_affinity": ["home", "cozy"],
        "seo_keywords":  ["sunset photography aesthetic", "golden hour landscape", "nature photography viral"],
        "tags":          ["GoldenHourVibes", "CinematicNature", "SunsetReflection", "LandscapeAesthetic", "NaturePhotography"],
    },

    # ── 3. HYGGE COZY ARCHITECTURE ────────────────────────────────────────────
    "hygge_cozy_architecture": {
        "label":         "Hygge Cozy Architecture",
        "description":   "Intimate reading nook bathed in candlelight — exposed rough stone wall, reclaimed timber ceiling beams, chunky knit wool throw, a steaming mug resting on a weathered oak surface, fairy lights twinkling in the background",
        "t2i_base":      (
            "cozy reading nook interior, exposed rough stone wall with moss texture, "
            "reclaimed rustic timber ceiling beams, chunky cable-knit wool throw blanket, "
            "steaming ceramic mug on weathered oak windowsill, "
            "warm candlelight and fairy string lights creating bokeh spheres, "
            "rain drops on window glass, foggy forest barely visible outside, "
            "2700K ultra-warm amber glow, deep rich shadows, "
            "shot on 50mm f/1.2 full frame DSLR, extreme shallow depth of field, "
            "intimate editorial interior photography, hygge lifestyle magazine spread, "
            "Kinfolk magazine aesthetic"
        ),
        "niche_affinity": ["cozy", "home"],
        "seo_keywords":  ["cozy bedroom aesthetic", "reading nook accessories", "warm night light", "ambient room lighting"],
        "tags":          ["CozyAesthetic", "HyggeHome", "ReadingNook", "CozyVibes", "WarmInterior"],
    },

    # ── 4. KAWAII PASTEL GAMING SETUP ─────────────────────────────────────────
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

    # ── 5. COTTAGECORE FAIRY DREAM ────────────────────────────────────────────
    "cottagecore_fairy_dream": {
        "label":         "Cottagecore Fairy Dream",
        "description":   "An enchanted lakeside cottage at dusk, nestled beneath a magical tree with lanterns swaying from every branch — warm light pouring from arched cottage windows, pebble shores, flowers cascading everywhere",
        "t2i_base":      (
            "enchanted fairytale cottage on rocky lakeside island, "
            "ancient gnarled tree with hundreds of hanging vintage brass lanterns glowing warm gold, "
            "pastel bokeh orbs in the canopy — peach cream teal, "
            "ivy-covered white stone cottage walls, arched mullioned windows with warm interior light, "
            "flowering vines cascading over entrance, stone steps to water's edge, "
            "smooth rounded river pebbles shore, still reflective water at dusk, "
            "pastel sunset sky in peach and rose gold, "
            "dreamy painterly hyperrealism, Pixar concept art quality, "
            "shot on 85mm portrait lens, extreme fine detail, "
            "whimsical atmosphere, magical realism style"
        ),
        "niche_affinity": ["home", "cozy"],
        "seo_keywords":  ["cottagecore aesthetic", "fairytale home", "cozy bedroom aesthetic", "kawaii room decor"],
        "tags":          ["CottagecoreAesthetic", "FairytaleDream", "MagicalHome", "EnchantedGarden", "WhimsicalDecor"],
    },

    # ── 6. COTTAGECORE TECH DEN ───────────────────────────────────────────────
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

    # ── 6b. SAGE CLEAN WORKSPACE ──────────────────────────────────────────────
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
        "tags":          ["SageGreenDesk", "AestheticWorkspace", "CleanDeskSetup", "ProductivityAesthetic", "KEsteticDesk"],
    },

    # ── 6c. WARM MINIMALIST BEDSIDE TECH ─────────────────────────────────────
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

    # ── 7. NEON MIRROR VANITY ─────────────────────────────────────────────────
    "neon_mirror_vanity": {
        "label":         "Neon Mirror Vanity",
        "description":   "A round gold-frame wall mirror adorned with lush red dahlias and magnolia leaves — delicate fairy light strings wrapping the frame, pillar candles glowing below, warm cream walls",
        "t2i_base":      (
            "round oversized gold brass frame mirror on cream textured wall, "
            "fresh red dahlia blooms and magnolia leaves arranged at top and bottom of mirror, "
            "delicate warm white fairy string lights draped around entire mirror circumference, "
            "three white pillar candles and two votive tea lights on shelf below, "
            "warm candlelight reflections on mirror glass, "
            "mirror reflecting soft room interior, "
            "cream and gold warm color palette, "
            "2400K ultra-warm ambient light, deep black shadows, "
            "interior lifestyle photography on Canon R6 50mm f/1.4, "
            "editorial home decor photography, Pinterest viral composition"
        ),
        "niche_affinity": ["home", "cozy"],
        "seo_keywords":  ["aesthetic room decor", "cute room decor", "led room lighting aesthetic", "minimalist home accessories"],
        "tags":          ["MirrorDecor", "FairyLightAesthetic", "FlowerDecor", "VanityGoals", "HomeDecorInspo"],
    },

    # ── 8. CELESTIAL LED ART ──────────────────────────────────────────────────
    "celestial_led_art": {
        "label":         "Celestial LED Art",
        "description":   "A sculptural white willow branch spreading across an entire wall — every twig tipped with a cold-white LED star, galaxy of lights against a warm grey wall, like a frozen winter constellation",
        "t2i_base":      (
            "large sculptural white willow tree branch wall art installation, "
            "hundreds of individual cold white LED starbursts on every twig and branch tip, "
            "warm taupe grey interior wall background, "
            "dark rich wood console table below with decorative objects, "
            "branch creating dramatic asymmetric composition across wall, "
            "LEDs creating star-cluster effect in room darkness, "
            "surrounding decor: glass globe paperweights, framed botanical prints, "
            "shot on Nikon Z9 35mm in low light, "
            "minimal ambient room light to enhance LED drama, "
            "luxury interior installation photography, Dwell magazine aesthetic"
        ),
        "niche_affinity": ["home", "smarthome"],
        "seo_keywords":  ["led room lighting aesthetic", "smart rgb led strip", "aesthetic room decor", "wall art decor"],
        "tags":          ["LEDArtInstallation", "CelestialDecor", "WallArtAesthetic", "StarLightVibes", "HomeInspo"],
    },

    # ── 9. VIBRANT MONOCHROME INTERIOR ────────────────────────────────────────
    "vibrant_monochrome": {
        "label":         "Vibrant Monochrome Interior",
        "description":   "A luxury living room drenched entirely in one saturated color — chartreuse green sofa, lime green shag rug, sage walls, emerald curtains, crystal chandelier above — bold, maximalist, magazine-cover power",
        "t2i_base":      (
            "luxury maximalist monochromatic living room, "
            "chartreuse lime green L-shape velvet sectional sofa with matching ottoman, "
            "sage green painted walls and matching ceiling with recessed cove LED strips, "
            "floor-to-ceiling emerald silk curtains with natural light behind, "
            "lime green ultra-shag high-pile rug, "
            "crystal and gold brass chandelier, chrome side tables, "
            "botanical art prints in white frames, green apple centerpiece, "
            "polished marble-effect floor reflecting room, "
            "interior architectural photography Canon TS-E 24mm tilt-shift, "
            "perfect symmetry, straight lines, magazine cover composition, "
            "Elle Decor / Vogue Living editorial quality, ultra-vibrant color"
        ),
        "niche_affinity": ["home"],
        "seo_keywords":  ["maximalist home decor", "luxury interior design", "bold living room decor", "aesthetic room decor"],
        "tags":          ["MaximalistDecor", "MonochromeInterior", "BoldHomeDecor", "LuxuryLiving", "ColorfulHome"],
    },

    # ── 10. CINEMATIC RETRO SCENES ────────────────────────────────────────────
    "cinematic_retro": {
        "label":         "Cinematic Retro Scenes",
        "description":   "A vintage red Volkswagen Beetle parked at a white English rose cottage — blood-red climbing roses overwhelming every surface, cobblestone driveway, slate roof, mature forest backdrop",
        "t2i_base":      (
            "vintage red Volkswagen Beetle classic car from rear three-quarter angle, "
            "white-painted English country cottage with grey slate roof behind, "
            "blood red climbing roses and creeping vines consuming cottage walls and fence, "
            "red window frames and matching front door with brass knocker, "
            "cobblestone driveway with fallen rose petals scattered, "
            "lush mature deciduous forest background, overcast diffused light, "
            "film grain texture, Kodak Portra 400 color simulation, "
            "slightly desaturated greens with punchy reds, "
            "shot on 35mm prime lens medium format Hasselblad style, "
            "editorial fashion meets architectural photography, "
            "nostalgic romantic English countryside mood"
        ),
        "niche_affinity": ["home", "cozy"],
        "seo_keywords":  ["cottagecore aesthetic", "vintage car aesthetic", "rose garden aesthetic", "cinematic photography"],
        "tags":          ["CinematicRetro", "CottageAesthetic", "VintageVibes", "RoseGarden", "EnglishCottage"],
    },
}

# ══════════════════════════════════════════════════════════════════════════════
# NICHE → VISUAL STYLE mapping (for analytics-informed routing)
# ══════════════════════════════════════════════════════════════════════════════
NICHE_STYLE_MAP = {
    "home":      ["biophilic_luxury", "hygge_cozy_architecture", "neon_mirror_vanity", "vibrant_monochrome"],
    "kitchen":   ["biophilic_luxury", "vibrant_monochrome", "hygge_cozy_architecture"],
    "cozy":      ["hygge_cozy_architecture", "cottagecore_fairy_dream", "neon_mirror_vanity", "cinematic_retro"],
    "gadgets":   ["kawaii_pastel_gaming", "warm_minimalist_bedside"],
    "organize":  ["sage_clean_workspace", "biophilic_luxury"],
    "tech":      ["kawaii_pastel_gaming", "sage_clean_workspace"],
    "budget":    ["sage_clean_workspace", "warm_minimalist_bedside"],
    "phone":     ["warm_minimalist_bedside", "kawaii_pastel_gaming"],
    "smarthome": ["warm_minimalist_bedside", "celestial_led_art"],
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
"""

# ══════════════════════════════════════════════════════════════════════════════
# ACCOUNT PROFILES — Audience-specific art direction personas
# ══════════════════════════════════════════════════════════════════════════════
_ACCOUNT_PROFILES = {
    "account_1": (
        "ACCOUNT: HomeDecor & Lifestyle (account_1)\n"
        "Audience: Homemakers, interior design aspirants, nesting millennials — 18-45, female-skewed, USA/UK/India\n"
        "Preferred Visual Styles: biophilic_luxury, hygge_cozy_architecture, neon_mirror_vanity, cottagecore_fairy_dream, vibrant_monochrome, celestial_led_art, cinematic_retro\n"
        "Tone: Sensory, intimate, aspirational — like a stylish friend sharing a room that stopped her mid-scroll\n"
        "Copy Voice: 'This corner of the world exists and you deserve to live in it'\n"
        "Goal: Maximum saves via pure aesthetic visual desire — every pin should make someone want to recreate it"
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
        "strategy":      "Biophilic Luxury Fallback",
        "visual_style":  "biophilic_luxury",
        "vibe":          "Monstera shadows on cream plaster, rattan chair, afternoon gold light flooding in",
        "title":         "This Room Taught Me What 'Home' Actually Feels Like",
        "description":   (
            "Afternoon light pours through arched windows and splits into a thousand shadows across the wall — "
            "each one the silhouette of a leaf, alive and moving. "
            "Rattan, terracotta, linen. The kind of space that makes you exhale the moment you walk in."
        ),
        "tags":          ["BiophilicDesign", "LuxuryInterior", "IndoorPlantAesthetic", "HomeDecorInspo", "NaturalLiving"],
        "visual_prompt": (
            "biophilic luxury interior, towering monstera deliciosa, arched floor-to-ceiling windows, "
            "cream plaster walls, dramatic leaf shadow patterns, rattan accent chair, terracotta ceramic pots, "
            "brushed-gold hardware, linen curtains, warm 3200K ambient light, "
            "editorial interior photography Canon EOS R5 35mm f/1.8, shallow depth of field, "
            "Architectural Digest style, magazine-worthy composition, "
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

10 VISUAL STYLES (pick the one matching analytics momentum + account audience)
{styles_str}

PIN SPECIFICATIONS
Image ratio: {ratio_cfg['label']} ({ratio_cfg['w']}x{ratio_cfg['h']}px)
Pin type: VIRAL_PIN — 100% editorial aesthetic AI-generated image. Zero products. Zero text in image.

CREATIVE DIRECTION
1. STYLE SELECTION
   - Study analytics profile (High-Impression / Low-Engagement → bolder visual hook needed).
   - Pick the Visual Style with momentum OR best fitting account audience preference.
   - If stagnant analytics: pick a DIFFERENT style than the default fallback to force fresh content.

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
       "I Didn't Know A Desk Could Make Work Feel Sacred"
   - Description: 2-3 sentences. Pure sensory and emotional pull. 
     Mention one specific texture, one specific light quality, one specific feeling.
     Never describe the image. Make the reader FEEL the image.

4. TAGS: CamelCase, no hashtag, exactly 5, SEO-optimized for Pinterest discoverability.

OUTPUT FORMAT (JSON only — no other text before or after)
{{
  "pin_type": "VIRAL_PIN",
  "strategy": "<brief name for this specific creative direction>",
  "visual_style": "<exact key from the 10 styles above>",
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
    Node 2 — CMO Mastermind [Elite Visual v3]
    Always VIRAL_PIN. 10 visual styles. Ultra-realistic T2I prompts. Elite copy.
    Primary: Gemini | Fallback: Cerebras | Last resort: hardcoded strategy
    """
    trigger = state.get("cycle_trigger", "")

    only_a1 = "account1" in trigger and "account2" not in trigger
    only_a2 = "account2" in trigger and "account1" not in trigger
    run_a1  = not only_a2
    run_a2  = not only_a1

    label = "A1 only" if only_a1 else ("A2 only" if only_a2 else "Both")
    logger.info(f"[Node 2 - CMO] VIRAL_PIN Elite Visual v3 | {label} | trigger={trigger}")

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
