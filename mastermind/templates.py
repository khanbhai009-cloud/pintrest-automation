"""
mastermind/templates.py
Local copy fallback templates — used when BOTH Groq AND Cerebras fail.
Guaranteed non-empty strings, niche-specific, Pinterest-optimised.
"""

LOCAL_TEMPLATES: dict = {
    # ── Account 1 niches ────────────────────────────────────────────────
    "home": {
        "title": "Hidden Gem Home Decor That Transforms Any Room ✨",
        "description": (
            "Struggling to make your space feel Pinterest-worthy? This aesthetic home "
            "essential is the missing piece. Minimalist design meets everyday function. "
            "Loved by thousands of home decor enthusiasts worldwide. "
            "Shop now via link in bio before it sells out! 🏡"
        ),
        "tags": ["HomeDecorIdeas", "AestheticRoom", "MinimalistHome", "HomeFinds", "RoomDecor"],
    },
    "kitchen": {
        "title": "Genius Kitchen Gadget That Saves 30 Min Every Day 🍳",
        "description": (
            "This viral kitchen tool is taking over Pinterest for good reason — it actually "
            "works. Saves prep time, looks stunning on any countertop, and makes cooking "
            "feel effortless. Thousands of home cooks already made the switch. "
            "Grab yours via link in bio! ✨"
        ),
        "tags": ["KitchenGadgets", "KitchenHacks", "CookingEssentials", "HomeChef", "KitchenOrganization"],
    },
    "cozy": {
        "title": "Cozy Room Essential You Didn't Know You Needed 🕯️",
        "description": (
            "Create your dream cozy corner with this aesthetic must-have. Warm ambiance, "
            "soft textures, instant vibe upgrade — this piece does it all. "
            "Perfect for autumn nights, reading sessions, and self-care Sundays. "
            "Shop via link in bio! 🍂"
        ),
        "tags": ["CozyRoom", "AestheticHome", "ReadingNook", "CozyVibes", "HomeAesthetic"],
    },
    "gadgets": {
        "title": "Problem-Solving Home Gadget Everyone Is Buying Right Now 🔧",
        "description": (
            "This clever home gadget solves the daily frustration you didn't realise "
            "had a fix. Compact, easy to use, and insanely satisfying. "
            "Hundreds of 5-star reviews don't lie. "
            "Link in bio — thank yourself later! 🙌"
        ),
        "tags": ["HomeGadgets", "SmartHome", "GadgetLovers", "LifeHacks", "MustHaveGadgets"],
    },
    "organize": {
        "title": "Aesthetic Storage Solution That Makes Decluttering Actually Fun 📦",
        "description": (
            "Finally, an organizer that looks as good as it works. Clear lines, "
            "satisfying layout, and a system that actually sticks. "
            "Transform any drawer, shelf, or closet in minutes. "
            "Shop via link in bio — your future self will thank you! ✨"
        ),
        "tags": ["HomeOrganization", "ClutterFree", "OrganizeWithMe", "AestheticStorage", "MinimalistLiving"],
    },

    # ── Account 2 niches ────────────────────────────────────────────────
    "tech": {
        "title": "This Cool Tech Gadget Just Made My Setup 10x Better 💻",
        "description": (
            "Upgrade your desk setup with this sleek tech essential everyone is obsessing "
            "over right now. Combines premium aesthetics with serious performance. "
            "Whether you're working, gaming, or creating — this belongs on your desk. "
            "Shop via link in bio! ⚡"
        ),
        "tags": ["DeskSetup", "TechGadgets", "SetupTour", "GadgetLovers", "TechFinds"],
    },
    "budget": {
        "title": "Under $20 Tech Find That Feels Like It Costs $200 💸",
        "description": (
            "Don't sleep on this budget tech gem — it punches way above its price tag. "
            "Compact, surprisingly powerful, and ships fast. "
            "One of those rare finds you'll wonder how you lived without. "
            "Grab it via link in bio before the price jumps! 🔥"
        ),
        "tags": ["BudgetTech", "CheapGadgets", "TechDeals", "GadgetUnder20", "AmazonFinds"],
    },
    "phone": {
        "title": "Viral Phone Accessory That's All Over TikTok & Pinterest 📱",
        "description": (
            "This aesthetic phone accessory is selling out fast — and it's easy to see why. "
            "Instantly upgrades your phone setup, protects your device, and looks stunning. "
            "Loved by creators, students, and professionals alike. "
            "Shop via link in bio! ✨"
        ),
        "tags": ["PhoneAccessories", "iPhoneAesthetic", "PhoneCase", "MagsafeAccessories", "TechAesthetic"],
    },
    "smarthome": {
        "title": "Smart Home Upgrade That Feels Like Living in the Future 🏠",
        "description": (
            "Control your entire vibe with this smart home essential. "
            "Voice control, app syncing, and energy-saving tech packed into one sleek device. "
            "Your home deserves a glow-up — this is how you do it. "
            "Link in bio to shop now! 💡"
        ),
        "tags": ["SmartHome", "HomeAutomation", "SmartLighting", "FuturisticHome", "TechHome"],
    },
    "wfh": {
        "title": "Work From Home Upgrade That Boosts Productivity Instantly 🖥️",
        "description": (
            "Struggling to focus at your home desk? This ergonomic WFH essential is the "
            "upgrade your setup is missing. Better posture, less fatigue, more output. "
            "Top-rated by remote workers and creators worldwide. "
            "Shop via link in bio! 🚀"
        ),
        "tags": ["WorkFromHome", "DeskSetup", "HomeOffice", "ProductivityHacks", "WFHEssentials"],
    },

    # ── Universal default ────────────────────────────────────────────────
    "default": {
        "title": "Amazing Find That's Taking Over Pinterest Right Now ✨",
        "description": (
            "This product is a total game-changer — and the reviews prove it. "
            "Sleek design, premium quality, real results. "
            "Thousands already love it and you'll see why the moment it arrives. "
            "Shop now via link in bio! 🔥"
        ),
        "tags": ["AmazonFinds", "MustHave", "PinterestFinds", "ViralProducts", "TrendingNow"],
    },
}
