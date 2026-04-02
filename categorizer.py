"""
CastForge Product Categorizer
Keyword-scoring engine that assigns products to the correct collection.
"""

import json
import re
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# CATEGORY TAXONOMY — handle → (keywords, negative_keywords)
# ═══════════════════════════════════════════════════════════════

# Words that mean "this is a figure product, NEVER Accessories"
FIGURE_KEYWORDS = {
    "soldier", "warrior", "knight", "figure", "bust", "tank", "ship",
    "aircraft", "plane", "dragon", "monster", "creature", "mech", "robot",
    "anime", "samurai", "viking", "roman", "german", "soviet", "american",
    "british", "french", "japanese", "medieval", "ancient", "modern",
    "ww2", "wwii", "ww1", "wwi", "napoleonic", "civil war", "infantry",
    "cavalry", "officer", "commander", "sniper", "pilot", "crew", "gunner",
    "archer", "musketeer", "legion", "centurion", "gladiator", "spartan",
    "crusader", "templar", "pirate", "cowboy", "zombie", "vampire",
    "werewolf", "demon", "angel", "elf", "dwarf", "orc", "goblin",
    "wizard", "witch", "skeleton", "undead", "trooper", "paratrooper",
    "commando", "ranger", "marine", "seal", "special forces",
    "barbarian", "berserker", "ronin", "paladin", "assassin",
}

CATEGORIES = {
    # ── Checked FIRST: specific figure/model categories ──
    "wargaming-infantry": {
        "keywords": [
            "soldier", "infantry", "troops", "rifleman", "gunner", "sniper",
            "commando", "paratrooper", "ranger", "marine", "crew", "officer",
            "grenadier", "medic", "sergeant", "lieutenant", "captain", "general",
            "ww2", "wwii", "ww1", "wwi", "world war", "vietnam", "korea",
            "civil war", "napoleonic", "german soldier", "american soldier",
            "soviet soldier", "british soldier", "french soldier",
            "surrendering", "artilleryman", "pilot", "navy seal",
        ],
        "negative": ["vehicle", "bust", "terrain", "building", "base",
                      "plinth", "tank", "aircraft", "ship"],
    },
    "scale-military-vehicles": {
        "keywords": [
            "tank", "panzer", "halftrack", "armored car", "jeep", "truck",
            "artillery", "cannon", "howitzer", "mortar", "apc", "ifv",
            "armored vehicle", "sdkfz", "t-34", "tiger", "sherman",
            "panther", "leopard", "abrams", "stug", "afv",
        ],
        "negative": ["bust", "figure", "aircraft", "ship", "plane", "boat"],
    },
    "scale-ships-naval": {
        "keywords": [
            "ship", "boat", "submarine", "destroyer", "battleship", "cruiser",
            "carrier", "frigate", "corvette", "u-boat", "naval", "admiral",
            "sailor", "navy", "warship", "bismarck", "yamato",
        ],
        "negative": ["tank", "aircraft", "bust", "plane", "car",
                      "soldier", "warrior", "knight", "anime", "dragon"],
    },
    "scale-aircraft": {
        "keywords": [
            "aircraft", "plane", "airplane", "fighter", "bomber", "helicopter",
            "spitfire", "mustang", "messerschmitt", "zero", "aviation",
            "lancaster", "corsair", "hurricane", "jet fighter", "apache",
        ],
        "negative": ["tank", "ship", "bust", "infantry", "car",
                      "soldier", "warrior", "knight", "anime", "dragon"],
    },
    "wargaming-heroes-characters": {
        "keywords": [
            "hero", "commander", "captain", "general", "warlord", "champion",
            "leader", "wizard", "sorcerer", "mage", "warlock", "paladin",
            "lord", "king", "queen", "assassin", "rogue", "ranger",
            "commissar", "inquisitor", "chaplain", "necromancer",
            "ronin", "gunslinger", "thief",
        ],
        "negative": ["vehicle", "terrain", "tank", "aircraft"],
    },
    "fantasy-warriors": {
        "keywords": [
            "fantasy", "barbarian", "viking", "gladiator", "samurai",
            "knight", "crusader", "warrior", "archer", "swordsman",
            "spartan", "centurion", "legionary", "roman", "medieval",
            "templar", "musketeer", "pirate", "cowboy", "amazon",
            "valkyrie", "berserker", "conan", "dark elf", "elven",
            "goddess", "angel", "female warrior",
        ],
        "negative": ["vehicle", "terrain", "tank", "aircraft",
                      "1/64", "1/100", "1/144", "garage"],
    },
    "wargaming-monsters-creatures": {
        "keywords": [
            "monster", "creature", "beast", "demon", "daemon", "dragon",
            "hydra", "wyrm", "wyvern", "giant", "troll", "ogre",
            "minotaur", "cthulhu", "eldritch", "xenomorph", "chimera",
            "cerberus", "griffin", "phoenix", "kraken", "alien", "predator",
        ],
        "negative": ["vehicle", "terrain", "tank", "aircraft"],
    },
    "busts-portraits": {
        "keywords": [
            "bust", "portrait", "torso", "half body", "head sculpt",
            "display bust", "resin bust", "museum piece", "pedestal",
            "200mm", "150mm", "100mm", "90mm", "75mm",
            "1/10", "1/9", "1/8",
        ],
        "negative": ["infantry", "vehicle", "terrain", "army", "troops",
                      "1/64", "1/35", "1/72", "1/48", "1/100", "1/144",
                      "school", "schoolgirl"],
    },
    "scifi-figures": {
        "keywords": [
            "sci-fi", "cyberpunk", "robot", "android", "cyborg",
            "power armor", "post-apocalyptic", "science fiction",
            "space marine", "mecha pilot", "starship trooper",
        ],
        "negative": ["tank", "terrain"],
    },
    "anime-characters": {
        "keywords": [
            "anime", "manga", "schoolgirl", "school girl", "waifu",
            "bishoujo", "chibi", "cosplay", "maid", "otaku", "kawaii",
            "japanese school",
        ],
        "negative": ["tank", "vehicle", "terrain", "building"],
    },
    "wargaming-vehicles-mechs": {
        "keywords": [
            "mech", "mecha", "gundam", "battletech", "titan", "walker",
            "dreadnought", "warjack", "battle suit", "war machine",
            "stompa", "gorkanaut", "sentinel",
        ],
        "negative": ["bust", "infantry", "troops", "terrain"],
    },
    "scale-cars-motorcycles": {
        "keywords": [
            "car model", "race car", "rally", "f1", "formula", "motorcycle",
            "motorbike", "muscle car", "classic car", "sports car",
            "hot rod", "drag car", "supercar",
        ],
        "negative": ["tank", "aircraft", "ship", "bust", "infantry",
                      "soldier", "warrior", "knight", "dragon", "vampire",
                      "anime", "figure", "armored car", "fantasy"],
    },
    "wargaming-army-bundles": {
        "keywords": [
            "army", "bundle", "starter set", "set of", "warband",
            "regiment set", "army box", "kill team", "patrol",
            "squad pack", "platoon",
        ],
        "negative": ["bust", "terrain", "single"],
    },

    # ── Terrain & Diorama ──
    "terrain-buildings-ruins": {
        "keywords": [
            "building", "ruin", "ruins", "tower", "castle", "church",
            "temple", "house", "fortress", "bunker", "watchtower",
            "trench", "gate", "arch", "column", "fountain",
        ],
        "negative": ["bust", "figure", "vehicle", "infantry"],
    },
    "terrain-scenery": {
        "keywords": [
            "scenery", "scatter terrain", "barricade", "wall", "fence",
            "crate", "barrel", "campfire", "bridge",
        ],
        "negative": ["bust", "figure", "vehicle", "infantry"],
    },
    "terrain-natural": {
        "keywords": [
            "tree", "forest", "rock", "boulder", "cliff", "hill", "river",
            "waterfall", "mountain", "mushroom", "crystal", "cave", "swamp",
        ],
        "negative": ["bust", "figure", "vehicle", "infantry", "building"],
    },
    "terrain-bases-plinths": {
        "keywords": [
            "base", "plinth", "display base", "scenic base", "round base",
            "movement tray", "magnetic base",
        ],
        "negative": ["bust", "figure", "infantry", "vehicle"],
    },
    "terrain-props": {
        "keywords": [
            "weapon rack", "treasure chest", "throne", "altar", "portal",
            "tombstone", "grave", "cart", "wagon", "tent", "flag", "banner",
            "sign", "cross", "barrel", "crate",
        ],
        "negative": ["bust", "infantry", "vehicle", "figure", "warrior",
                      "knight", "soldier", "75mm", "90mm", "200mm",
                      "1/10", "1/35"],
    },

    # ── Accessories: ONLY actual hobby supplies ──
    "accessories": {
        "keywords": [
            "paint set", "brush set", "airbrush kit", "airbrush needle",
            "cutting mat", "hobby knife", "pin vise", "display case",
            "wet palette", "work mat", "work pad", "hobby mat",
            "silicone mat", "silicone pad",
            "static grass", "green stuff", "milliput", "sculpting putty",
            "hobby tool", "hobby lamp", "magnifying glass", "magnifying lamp",
            "airbrush compressor", "spray booth", "paint rack",
            "basing material", "flock mix",
            "airbrush", "tweezers", "turntable", "organizer",
            "led light", "led lamp",
        ],
        "negative": list(FIGURE_KEYWORDS),  # ALL figure words are negative
    },
}

# Parent collection mapping
PARENT_COLLECTIONS = {
    "wargaming-infantry": "wargaming-tabletop",
    "wargaming-vehicles-mechs": "wargaming-tabletop",
    "wargaming-monsters-creatures": "wargaming-tabletop",
    "wargaming-heroes-characters": "wargaming-tabletop",
    "wargaming-army-bundles": "wargaming-tabletop",
    "scale-military-vehicles": "scale-model-kits",
    "scale-aircraft": "scale-model-kits",
    "scale-ships-naval": "scale-model-kits",
    "scale-cars-motorcycles": "scale-model-kits",
    "anime-characters": "anime-fantasy-figures",
    "fantasy-warriors": "anime-fantasy-figures",
    "scifi-figures": "anime-fantasy-figures",
    "busts-portraits": "anime-fantasy-figures",
    "terrain-bases-plinths": "diorama-terrain",
    "terrain-scenery": "diorama-terrain",
    "terrain-buildings-ruins": "diorama-terrain",
    "terrain-natural": "diorama-terrain",
    "terrain-props": "diorama-terrain",
    "accessories": "accessories",
}

# ═══════════════════════════════════════════════════════════════
# TITLE CLEANING
# ═══════════════════════════════════════════════════════════════

# Longest phrases first so they match before shorter substrings
ALIEXPRESS_JUNK = [
    # Multi-word phrases (longest first)
    "colorless and self-assembling", "colorless and self-assembled",
    "display collection decoration", "collection decoration",
    "figure model kit", "character model", "model kit figure",
    "action figure collectib", "creative photography", "creative display",
    "micro creative", "props creative", "model props",
    "3d resin printing", "3d printing", "hand painted", "handpainted",
    "diy craft toys", "diy craft", "garage scenes", "garage scene",
    "scene matching", "anime figure", "free shipping", "hot sale",
    "new arrival", "best quality", "high quality", "top quality",
    "brand new", "factory direct", "limited time", "flash sale",
    "big sale", "fast delivery", "in stock", "in-stock", "us warehouse",
    "the height of man", "kits beauty", "kits toy",
    "self-assembling", "self-assembled", "self assembled",
    "die-cast", "die cast",
    "s toy",
    # Single words
    "wholesale", "dropship", "aliexpress", "cheap", "colorless",
    "collectible", "collectib", "miniatura", "minifigura",
    "minifigures", "minifigure", "assembly", "spot", "status",
]

# Brand names to strip
BRAND_NAMES = [
    "hobby mio", "mry-sfw", "yufan", "djmax", "tuskmodel", "jiestar",
    "figura", "resinkit", "modelon", "masterclub", "mantis miniatures",
    "nutsplanet", "jmini", "scale75", "amati", "italeri", "verlinden",
    "pegaso", "andrea", "celtic", "romeo", "el viejo dragon",
    "best soldiers", "alexandros", "penz", "alpine miniatures",
    "bravo6", "dolman", "jaguar", "legend", "mini art", "royal model",
    "stalingrad", "thor", "ultracast", "warriors", "wolf",
    "dna model", "meng", "trumpeter", "tamiya", "revell", "airfix",
    "hasegawa", "fujimi", "aoshima", "finemolds", "flyhawk",
    "mirage hobby", "master box", "ice model", "zkmodel", "corsar rex",
]

# Extra filler to strip
EXTRA_FILLER = [
    "resin kit", "model kit", "figure kit", "garage kit", "gk",
    "statue", "figurine", "character model", "action figure",
    "figure model", "scale model", "hobby", "collection", "decoration",
    "gift", "home decor", "desk decor", "for hobbyists", "for collectors",
    "for painters", "for modelers", "detail up", "spot goods",
    "3d printed", "3d print", "unassembled", "unpainted",
    "sculpture for hobbyists",
]

ALIEXPRESS_JUNK.extend(BRAND_NAMES)
ALIEXPRESS_JUNK.extend(EXTRA_FILLER)
ALIEXPRESS_JUNK.sort(key=len, reverse=True)

# Brand-code prefix pattern: MRY-SFW, ZK-001, YUFAN style codes at start
BRAND_CODE_PATTERN = re.compile(
    r"^[A-Z][A-Za-z]*[-_]?[A-Z0-9]{1,5}\s+",
)

JUNK_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(j) for j in ALIEXPRESS_JUNK) + r")\w*\b",
    re.IGNORECASE,
)

# Catalog number patterns:
# A-757, Td-3622, Hong-06, Bee-15  (Letter(s)-dash-digits)
# Jk12, Td4567                     (Upper+lower+digits, no dash)
# GW-15, TD-123                    (Uppercase-dash-digits)
# Excludes: WW2, WW1, F16, P51, T34, M16 (military designations)
_MILITARY_DESIGNATIONS = {"WW1", "WW2", "F16", "P51", "T34", "M16", "B17",
                           "ME109", "BF109", "FW190", "SU76", "IS2", "KV1"}
CATALOG_CODE_PATTERN = re.compile(
    r"\b[A-Z][a-z]\d{2,5}\b"       # Jk12, Td4567 (upper+lower+digits)
    r"|\b[A-Z][a-z]+-\d{1,5}\b"    # Td-3622, Hong-06, Bee-15
    r"|\b[A-Z]-\d{2,5}\b"          # A-757, A-914 (single letter-dash-digits)
    r"|\b[A-Z]{2,4}-\d{2,5}\b",    # GW-15, TD-4567 (multi upper-dash-digits)
    re.IGNORECASE,
)

DISCOUNT_PATTERN = re.compile(r"\d+%\s*off", re.IGNORECASE)
MULTI_SPACE = re.compile(r"\s{2,}")
SCALE_PATTERN = re.compile(r"(1[:/]\d{1,3})", re.IGNORECASE)
SCALE_MM_PATTERN = re.compile(r"(\d{2,3}\s*mm)", re.IGNORECASE)

MAX_TITLE_LENGTH = 60

_TITLE_TYPE_SUFFIX = {
    "busts-portraits": "Resin Bust",
    "terrain-bases-plinths": "Resin Terrain Base",
    "terrain-scenery": "Resin Terrain Piece",
    "terrain-buildings-ruins": "Resin Terrain Kit",
    "terrain-natural": "Resin Terrain",
    "terrain-props": "Resin Figure Set",
    "wargaming-infantry": "Resin Miniature",
    "wargaming-vehicles-mechs": "Resin Vehicle Kit",
    "wargaming-monsters-creatures": "Resin Creature Figure",
    "wargaming-heroes-characters": "Resin Character Figure",
    "wargaming-army-bundles": "Resin Army Set",
    "scale-military-vehicles": "Resin Model Kit",
    "scale-aircraft": "Resin Model Kit",
    "scale-ships-naval": "Resin Model Kit",
    "scale-cars-motorcycles": "Resin Model Kit",
    "anime-characters": "Resin Figure",
    "fantasy-warriors": "Resin Figure",
    "scifi-figures": "Resin Figure",
    "accessories": "Hobby Supply",
}

# AI title cache
_AI_TITLE_CACHE_FILE = Path("ai_title_cache.json")


def _load_title_cache():
    if _AI_TITLE_CACHE_FILE.exists():
        return json.loads(_AI_TITLE_CACHE_FILE.read_text())
    return {}


def _save_title_cache(cache):
    _AI_TITLE_CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False))


def clean_title(title, category_handle="wargaming-heroes-characters"):
    """
    Remove AliExpress spam, title-case, and limit to 60 chars.
    Format: descriptive name + scale + Resin Figure/Kit/Bust.
    """
    t = JUNK_PATTERN.sub("", title)
    t = DISCOUNT_PATTERN.sub("", t)
    # Strip brand-code prefixes at start of title
    t = BRAND_CODE_PATTERN.sub("", t)

    # Strip catalog codes (A-757, Td-3622, Hong-06, Jk12, etc.)
    # but preserve military designations (F16, T34, WW2, etc.)
    def _strip_catalog(m):
        code = m.group().upper()
        return m.group() if code in _MILITARY_DESIGNATIONS else ""
    t = CATALOG_CODE_PATTERN.sub(_strip_catalog, t)

    # Strip standalone 1-4 digit numbers that aren't scales or years
    # Preserves: 1/35 (scale), 54mm (scale), 1805 (year 1800-2099)
    # Uses lookahead/lookbehind to avoid eating scale components
    def _strip_standalone_number(m):
        num = m.group()
        full = m.string
        start = m.start()
        end = m.end()
        # Preserve if preceded by "/" (part of scale like 1/35)
        if start > 0 and full[start - 1] == "/":
            return num
        # Preserve if followed by "/" (part of scale like 1/35)
        if end < len(full) and full[end] == "/":
            return num
        # Preserve if followed by "mm" (scale like 54mm)
        if end < len(full) and full[end:end+2].lower() == "mm":
            return num
        # Preserve years 1800-2099
        if num.isdigit() and len(num) == 4 and 1800 <= int(num) <= 2099:
            return num
        return ""
    t = re.sub(r"(?<!/)\b\d{1,4}\b(?!mm|/)", _strip_standalone_number, t)

    # Remove orphaned punctuation and double spaces
    t = re.sub(r"^\s*[,\-–—]\s*", "", t)
    t = re.sub(r"\s*[,\-–—]\s*$", "", t)
    t = MULTI_SPACE.sub(" ", t).strip()

    # Extract scale before title-casing
    scale = ""
    m = SCALE_PATTERN.search(t)
    if m:
        scale = m.group(1).replace(":", "/")
    else:
        m = SCALE_MM_PATTERN.search(t)
        if m:
            scale = m.group(1).strip().lower()

    # Title-case but preserve scale notations
    scales_found = SCALE_PATTERN.findall(t)
    mm_found = SCALE_MM_PATTERN.findall(t)
    t = t.title()
    for s in scales_found:
        t = re.sub(re.escape(s.title()), s, t, flags=re.IGNORECASE)
    for s in mm_found:
        t = re.sub(re.escape(s.title()), s.lower(), t, flags=re.IGNORECASE)

    # Restore common acronyms
    _ACRONYMS = {"Bbq": "BBQ", "Wwii": "WWII", "Ww2": "WW2", "Ww1": "WW1",
                 "Diy": "DIY", "Suv": "SUV", "Usa": "USA", "Led": "LED",
                 "Sdk": "SDK", "Atv": "ATV", "Sdkfz": "SdKfz"}
    for wrong, right in _ACRONYMS.items():
        t = re.sub(r"\b" + re.escape(wrong) + r"\b", right, t)

    # Build a clean title: strip scale and type words from desc,
    # then re-append scale + type suffix
    type_suffix = _TITLE_TYPE_SUFFIX.get(category_handle, "Resin Figure")

    desc = t
    desc = SCALE_PATTERN.sub("", desc)
    desc = SCALE_MM_PATTERN.sub("", desc)
    desc = re.sub(r"\b(?:Resin|Model|Kits?|Figure|Figures|Bust|Set|Scale|Diorama|"
                  r"Miniature|Miniatures|Sand|Table|Scene|Scence|Micro|"
                  r"Mini|Landscape|Arquitectura|Wt\d*|Pcs?|Handmade|Diy|"
                  r"Painted|Photography|Tiny|Static|Piece|Beauty|Toy|"
                  r"Assembly|Character|Portrait|Standing|Status|Spot|"
                  r"Die-?Cast)\b",
                  "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\s{2,}", " ", desc).strip()
    desc = re.sub(r"^\s*[,\-–—]\s*", "", desc).strip()
    desc = re.sub(r"\s*[,\-–—]\s*$", "", desc).strip()

    # Rebuild: desc + scale + type_suffix
    parts = [desc]
    if scale:
        parts.append(scale)
    parts.append(type_suffix)
    t = " ".join(p for p in parts if p)

    # Enforce 60-char limit
    if len(t) > MAX_TITLE_LENGTH:
        suffix_part = f" {scale} {type_suffix}" if scale else f" {type_suffix}"
        max_desc_len = MAX_TITLE_LENGTH - len(suffix_part)
        if max_desc_len > 5:
            desc = desc[:max_desc_len].rsplit(" ", 1)[0].rstrip(" ,—-–")
            t = f"{desc}{suffix_part}"
        else:
            t = t[:MAX_TITLE_LENGTH].rsplit(" ", 1)[0].rstrip(" ,—-–")

    return t


def title_needs_ai(cleaned_title, raw_title):
    """Check if a cleaned title is garbage and needs AI rewriting."""
    # Strip the type suffix to check just the descriptive part
    desc = cleaned_title
    for suffix in _TITLE_TYPE_SUFFIX.values():
        if desc.endswith(suffix):
            desc = desc[:-(len(suffix))].strip()
            break

    # Remove scale from desc for length check
    desc_no_scale = SCALE_PATTERN.sub("", desc)
    desc_no_scale = SCALE_MM_PATTERN.sub("", desc_no_scale).strip()

    # Too short after cleaning = garbage
    if len(desc_no_scale) < 20:
        return True

    # Still has catalog codes
    if CATALOG_CODE_PATTERN.search(cleaned_title):
        return True

    return False


def ai_generate_titles_batch(products, api_key):
    """
    Batch-generate descriptive titles for products with garbage cleaned titles.
    Uses Claude with vision (title + image) for accuracy.
    Caches results in ai_title_cache.json.
    """
    import requests as req

    cache = _load_title_cache()
    needs_ai = []

    for p in products:
        raw = p.get("_raw_title", "")
        cleaned = p.get("title", "")
        if raw and title_needs_ai(cleaned, raw) and raw not in cache:
            needs_ai.append(p)
        elif raw in cache:
            # Apply cached title
            p["title"] = cache[raw]

    if not needs_ai:
        return

    print(f"  AI title generation for {len(needs_ai)} products (batches of 10)...")

    prompt = (
        "You are writing product names for CastForge, a premium resin miniature store.\n\n"
        "Given this raw AliExpress product title, write a clean, compelling product name.\n\n"
        "RULES:\n"
        "- Be SPECIFIC: describe what the figure/model actually depicts\n"
        "- Include the ERA or SETTING (WWII, Medieval, Fantasy, Sci-Fi, Modern)\n"
        "- Include NATIONALITY or FACTION if military (German, Soviet, American, British)\n"
        "- Include the ROLE or TYPE (Officer, Sniper, Knight, Dragon, Tank Crew)\n"
        "- Include the SCALE if present in the original title (1/35, 75mm, etc.)\n"
        "- DO NOT include: brand names, catalog numbers, 'resin', 'model kit', "
        "'figure', 'unpainted', 'unassembled', 'sculpture', 'for hobbyists'\n"
        "- DO NOT start with generic words like 'The', 'A', 'New'\n"
        "- MAX 50 characters\n"
        "- The suffix 'Resin Figure' or 'Resin Bust' will be added automatically\n\n"
        "GOOD examples:\n"
        "WWII German Panzer Commander 1/35\n"
        "Medieval Teutonic Knight 54mm\n"
        "Viking Berserker with Battle Axe 75mm\n"
        "Vampire Selene Underworld Fantasy 1/24\n"
        "Napoleon at Austerlitz 90mm\n"
        "Modern US Navy SEAL Operator 1/35\n"
        "Fire Dragon with Treasure Hoard 75mm\n"
        "Silicone Hobby Work Pad\n\n"
        "BAD examples (don't do these):\n"
        "Figure Model Kit 295\n"
        "Mry-Sfw Detail Up American\n"
        "Unassembled Sculpture For Hobbyists\n"
        "Standing Male Character\n\n"
        "Raw title: {raw_title}\n\n"
        "Write ONLY the product name, nothing else."
    )

    generated = 0
    errors = 0
    for i in range(0, len(needs_ai), 10):
        batch = needs_ai[i:i + 10]

        for p in batch:
            raw = p.get("_raw_title", "")
            image_url = p.get("image_url", "")

            # Build message — text only (image URLs from AliExpress
            # often fail when Claude API tries to fetch them)
            content = [{
                "type": "text",
                "text": prompt.format(raw_title=raw),
            }]

            try:
                resp = req.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 60,
                        "messages": [{"role": "user", "content": content}],
                    },
                    timeout=15,
                )

                if resp.status_code == 200:
                    new_title = resp.json()["content"][0]["text"].strip()
                    new_title = new_title.strip('"\'')

                    # Ensure scale is included — but only if AI didn't already add one
                    has_scale = (re.search(r"\b\d{2,3}\s*mm\b", new_title, re.IGNORECASE)
                                 or re.search(r"\b1[:/]\d{1,3}\b", new_title))
                    if not has_scale:
                        scale = detect_scale(raw)
                        if scale:
                            new_title = f"{new_title} {scale}"

                    # Truncate if over 60
                    if len(new_title) > 60:
                        new_title = new_title[:60].rsplit(" ", 1)[0]

                    if len(new_title) > 5:
                        cache[raw] = new_title
                        p["title"] = new_title
                        generated += 1
                    else:
                        errors += 1
                        if errors <= 3:
                            print(f"    Bad AI response ({len(new_title)} chars): {new_title[:80]}")
                else:
                    errors += 1
                    if errors <= 3:
                        print(f"    API error {resp.status_code}: {resp.text[:150]}")

            except Exception as e:
                errors += 1
                if errors <= 3:
                    print(f"    Exception: {type(e).__name__}: {str(e)[:100]}")

        _save_title_cache(cache)
        done = min(i + 10, len(needs_ai))
        print(f"    [{done}/{len(needs_ai)}] generated")

        if i + 10 < len(needs_ai):
            import time
            time.sleep(0.5)

    print(f"  AI generated {generated} titles ({len(cache)} cached total)")


# ═══════════════════════════════════════════════════════════════
# SCALE DETECTION
# ═══════════════════════════════════════════════════════════════

def detect_scale(title):
    """Extract scale from title (e.g. '1/64', '28mm', '54mm')."""
    # Fraction scales
    m = re.search(r"1[:/](\d{1,3})", title)
    if m:
        return f"1/{m.group(1)}"
    # mm scales
    m = re.search(r"(\d{2,3})\s*mm", title, re.IGNORECASE)
    if m:
        return f"{m.group(1)}mm"
    return "Various"


# ═══════════════════════════════════════════════════════════════
# CATEGORIZATION
# ═══════════════════════════════════════════════════════════════

def categorize(title, description=""):
    """
    Fast-path keyword categorization for OBVIOUS cases only.
    Everything else returns needs_ai=True for batch AI processing.
    """
    t = f"{title} {description}".lower()

    # Fast-path: unambiguous keyword matches
    if any(w in t for w in ["brush", "airbrush", "cutting mat", "work pad",
                             "silicone mat", "hobby knife", "paint set",
                             "wet palette", "hobby tool", "hobby lamp"]):
        if not any(w in t for w in FIGURE_KEYWORDS):
            return "accessories", 10, "accessories"

    if any(w in t for w in ["tank", "panzer", "sherman", "tiger", "t-34",
                             "halftrack", "sdkfz", "howitzer"]):
        if not any(w in t for w in ["bust", "figure", "pilot", "crew"]):
            return "scale-military-vehicles", 10, "scale-model-kits"

    if any(w in t for w in ["dragon", "orc", "elf", "wizard", "goblin",
                             "warhammer", "undead", "necromancer", "demon"]):
        return "fantasy-warriors", 10, "anime-fantasy-figures"

    if any(w in t for w in ["anime", "manga", "waifu", "schoolgirl",
                             "school girl", "chibi", "kawaii"]):
        return "anime-characters", 10, "anime-fantasy-figures"

    if "bust" in t and any(w in t for w in ["1/10", "200mm", "150mm", "100mm"]):
        return "busts-portraits", 10, "anime-fantasy-figures"

    # Everything else → needs AI categorization
    # Return placeholder; ai_categorize_batch will override
    return "wargaming-heroes-characters", 0, "wargaming-tabletop"


# ═══════════════════════════════════════════════════════════════
# AI CATEGORIZATION (for products that score < 2 on keywords)
# ═══════════════════════════════════════════════════════════════

_AI_CACHE_FILE = Path("ai_category_cache.json")

_NAME_TO_HANDLE = None  # lazy init after CATEGORY_DISPLAY_NAMES is defined


def _get_name_to_handle():
    global _NAME_TO_HANDLE
    if _NAME_TO_HANDLE is None:
        _NAME_TO_HANDLE = {v: k for k, v in CATEGORY_DISPLAY_NAMES.items()}
    return _NAME_TO_HANDLE

_BATCH_AI_PROMPT = """Categorize each resin miniature product into exactly one category.

Categories with examples:
- infantry-troops: WW1/WW2/modern/historical soldiers, military personnel, generic unnamed troops. Examples: "WW2 German Sniper 1/35", "US Marine Vietnam 1/35", "Soviet Infantry Stalingrad"
- military-vehicles: tanks, APCs, artillery, military trucks. Examples: "Tiger Tank 1/35", "Sherman M4A3 1/72"
- ships-naval: warships, submarines, naval vessels, sailors. Examples: "HMS Victory 1/350", "U-Boat Type VII"
- aircraft: planes, helicopters, pilots. Examples: "Spitfire Mk.V 1/48", "Apache Helicopter 1/72"
- heroes-characters: ONLY named/notable individuals — historical leaders, movie characters, named warriors. Examples: "Napoleon at Waterloo 54mm", "Spartacus 75mm", "Vampire Selene 1/24"
- fantasy-warriors: dragons, elves, orcs, wizards, undead, dark fantasy. Examples: "Fire Dragon 75mm", "Orc Warboss", "Dark Elf Assassin"
- busts-portraits: bust/head/shoulder sculptures, typically 1/10 or larger. Examples: "Viking Warrior Bust 1/10", "Roman Centurion Bust 200mm"
- monsters-creatures: beasts, aliens, mythical creatures. Examples: "Xenomorph Alien 1/10", "Giant Spider"
- sci-fi-figures: robots, cyberpunk, space marines, futuristic. Examples: "Space Marine Commander", "Cyberpunk Samurai"
- anime-characters: anime/manga style, schoolgirls, chibi. Examples: "Anime Schoolgirl 1/24", "Manga Warrior Girl"
- vehicles-mechs: sci-fi vehicles, mechs, gundams. Examples: "Gundam RX-78", "Battle Mech Titan"
- cars-motorcycles: civilian vehicles, racing. Examples: "1967 Mustang 1/24", "Cafe Racer Motorcycle"
- buildings-ruins: terrain, buildings, ruins, diorama bases. Examples: "Ruined Church 1/35", "Medieval Castle Gate"
- natural-elements: trees, rocks, water features. Examples: "Oak Tree Set", "Rock Formation"
- props-accessories: standalone weapons, barrels, camp items. Examples: "Weapon Rack", "Wooden Barrel Set"
- army-bundles: sets of multiple figures. Examples: "WW2 German Squad 5-Pack"
- accessories: ONLY hobby tools/paints/brushes — NEVER figures. Examples: "Silicone Work Pad", "Airbrush Needle"

CRITICAL RULES:
- Generic unnamed soldiers ALWAYS go to infantry-troops, NOT heroes-characters
- heroes-characters is ONLY for specifically named/notable individuals
- If unsure between infantry-troops and heroes-characters, choose infantry-troops
- accessories is ONLY for non-figure hobby supplies
- busts-portraits is ONLY for bust-format sculptures (head/shoulders)

Products to categorize:
{products_list}

Reply with ONLY a JSON object mapping each product number to its category handle, like:
{{"1": "infantry-troops", "2": "heroes-characters", "3": "fantasy-warriors"}}"""


def _load_ai_cache():
    if _AI_CACHE_FILE.exists():
        return json.loads(_AI_CACHE_FILE.read_text())
    return {}


def _save_ai_cache(cache):
    _AI_CACHE_FILE.write_text(json.dumps(cache, indent=2))


def _ai_categorize(title):
    """Categorize a single product using Claude API, with cache."""
    cache = _load_ai_cache()
    if title in cache:
        handle = cache[title]
        parent = PARENT_COLLECTIONS.get(handle, "diorama-terrain")
        return handle, 1, parent

    # Queue for batch processing — return placeholder that will be
    # resolved by ai_categorize_batch. Heroes & Characters is a safer
    # default than Props/Accessories for figure products.
    return "wargaming-heroes-characters", 0, "wargaming-tabletop"


def ai_categorize_batch(products, api_key):
    """
    AI-first categorization. Sends products in batches of 20 to Claude.
    Only products with score 0 (not caught by keyword fast-path) need AI.
    """
    import requests as req
    import time as _time

    cache = _load_ai_cache()
    needs_ai = []
    cached_hits = 0

    for p in products:
        title = p.get("_raw_title", p.get("title", ""))
        score = p.get("_score", 0)

        # Already categorized by keyword fast-path (score >= 10)
        if score >= 2:
            continue

        if title in cache:
            handle = cache[title]
            parent = PARENT_COLLECTIONS.get(handle, "wargaming-tabletop")
            p["category_handle"] = handle
            p["parent_handle"] = parent
            p["product_type"] = PARENT_DISPLAY_NAMES.get(parent, "Wargaming & Tabletop")
            cached_hits += 1
        else:
            needs_ai.append((p, title))

    if cached_hits:
        print(f"  AI cache: applied {cached_hits} cached categories")

    if not needs_ai:
        return

    print(f"  AI categorizing {len(needs_ai)} products (batches of 20)...")

    batch_size = 20
    categorized = 0
    errors = 0

    for i in range(0, len(needs_ai), batch_size):
        batch = needs_ai[i:i + batch_size]

        # Build numbered product list for the prompt
        products_list = "\n".join(
            f"{j+1}. {title[:100]}" for j, (_, title) in enumerate(batch)
        )

        try:
            resp = req.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 500,
                    "messages": [{
                        "role": "user",
                        "content": _BATCH_AI_PROMPT.format(products_list=products_list),
                    }],
                },
                timeout=30,
            )

            if resp.status_code == 200:
                text = resp.json()["content"][0]["text"].strip()
                # Parse JSON from response (handle markdown code blocks)
                if text.startswith("```"):
                    text = re.sub(r"^```(?:json)?\s*", "", text)
                    text = re.sub(r"\s*```$", "", text)
                try:
                    results = json.loads(text)
                except json.JSONDecodeError:
                    # Try to extract JSON from response
                    m = re.search(r"\{[^}]+\}", text)
                    if m:
                        results = json.loads(m.group())
                    else:
                        errors += len(batch)
                        continue

                # Apply results
                name_map = _get_name_to_handle()
                for j, (product, title) in enumerate(batch):
                    key = str(j + 1)
                    handle = results.get(key, "wargaming-heroes-characters")

                    # Map display name to handle if needed
                    if handle not in PARENT_COLLECTIONS and handle not in ["accessories"]:
                        mapped = name_map.get(handle)
                        if mapped:
                            handle = mapped

                    # Validate
                    if handle not in PARENT_COLLECTIONS and handle != "accessories":
                        handle = "wargaming-heroes-characters"

                    cache[title] = handle
                    parent = PARENT_COLLECTIONS.get(handle, "wargaming-tabletop")
                    product["category_handle"] = handle
                    product["parent_handle"] = parent
                    product["product_type"] = PARENT_DISPLAY_NAMES.get(parent, "Wargaming & Tabletop")
                    categorized += 1

            else:
                errors += len(batch)
                if errors <= 3:
                    print(f"    API error {resp.status_code}: {resp.text[:100]}")

        except Exception as e:
            errors += len(batch)
            if errors <= 3:
                print(f"    Exception: {str(e)[:80]}")

        _save_ai_cache(cache)
        done = min(i + batch_size, len(needs_ai))
        print(f"    [{done}/{len(needs_ai)}] categorized")

        if i + batch_size < len(needs_ai):
            _time.sleep(0.5)

    print(f"  AI categorized {categorized} products, {errors} errors ({len(cache)} cached)")


def _call_claude_categorize(title, api_key):
    """Legacy single-product categorizer (kept for compatibility)."""
    import requests as req

    try:
        resp = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 30,
                "messages": [{
                    "role": "user",
                    "content": f"Categorize this resin miniature: {title}. Reply with ONLY the category handle from: infantry-troops, military-vehicles, ships-naval, aircraft, heroes-characters, fantasy-warriors, busts-portraits, monsters-creatures, sci-fi-figures, anime-characters, vehicles-mechs, cars-motorcycles, buildings-ruins, natural-elements, props-accessories, army-bundles, accessories. Generic soldiers→infantry-troops. Named characters→heroes-characters.",
                }],
            },
            timeout=10,
        )

        if resp.status_code == 200:
            answer = resp.json()["content"][0]["text"].strip()
            # Map display name back to handle
            name_map = _get_name_to_handle()
            handle = name_map.get(answer)
            if handle:
                return handle

            # Fuzzy match — find closest category name
            answer_lower = answer.lower()
            for name, h in name_map.items():
                if name.lower() in answer_lower or answer_lower in name.lower():
                    return h

    except Exception:
        pass

    # If API fails, fall back to Heroes & Characters (safer than Accessories)
    return "wargaming-heroes-characters"


def _validate_ai_category(handle, title):
    """
    Check if the AI-assigned category makes sense for the title.
    Returns the handle if valid, or the keyword categorizer's best guess.
    """
    t = title.lower()

    # Define absurd mismatches: category + title keywords that contradict
    _CONTRADICTIONS = {
        "scale-ships-naval": ["girl", "woman", "female", "student", "school",
                               "warrior", "knight", "soldier", "dragon",
                               "bust", "anime", "fantasy", "medieval"],
        "scale-aircraft": ["girl", "woman", "female", "student", "school",
                            "warrior", "knight", "bust", "dragon", "fantasy"],
        "scale-cars-motorcycles": ["girl", "woman", "female", "student",
                                    "warrior", "knight", "soldier", "bust",
                                    "dragon", "fantasy", "medieval"],
        "wargaming-vehicles-mechs": ["girl", "woman", "female", "student",
                                      "school", "bust", "anime", "dress"],
        "terrain-natural": ["girl", "woman", "female", "warrior", "knight",
                             "soldier", "bust", "anime", "figure"],
        "terrain-buildings-ruins": ["girl", "woman", "female", "warrior",
                                     "figure", "bust", "anime"],
        "accessories": list(FIGURE_KEYWORDS),
    }

    contradictions = _CONTRADICTIONS.get(handle, [])
    if any(word in t for word in contradictions):
        # AI got it wrong — use keyword categorizer's best guess
        best_handle, best_score, best_parent = categorize(title)
        if best_score >= 2:
            return best_handle
        # Keyword categorizer also failed — guess from title
        if any(w in t for w in ["bust", "portrait", "head"]):
            return "busts-portraits"
        if any(w in t for w in ["girl", "woman", "female", "anime", "school"]):
            return "anime-characters"
        if any(w in t for w in ["warrior", "knight", "soldier", "figure"]):
            return "fantasy-warriors"
        return "fantasy-warriors"  # safer default than ships/aircraft

    return handle


# ═══════════════════════════════════════════════════════════════
# DESCRIPTION GENERATION
# ═══════════════════════════════════════════════════════════════

CATEGORY_DISPLAY_NAMES = {
    "wargaming-infantry": "Infantry & Troops",
    "wargaming-vehicles-mechs": "Vehicles & Mechs",
    "wargaming-monsters-creatures": "Monsters & Creatures",
    "wargaming-heroes-characters": "Heroes & Characters",
    "wargaming-army-bundles": "Army Bundles",
    "scale-military-vehicles": "Military Vehicles",
    "scale-aircraft": "Aircraft",
    "scale-ships-naval": "Ships & Naval",
    "scale-cars-motorcycles": "Cars & Motorcycles",
    "anime-characters": "Anime Characters",
    "fantasy-warriors": "Fantasy Warriors",
    "scifi-figures": "Sci-Fi Figures",
    "busts-portraits": "Busts & Portraits",
    "terrain-bases-plinths": "Bases & Plinths",
    "terrain-scenery": "Scenery Pieces",
    "terrain-buildings-ruins": "Buildings & Ruins",
    "terrain-natural": "Natural Elements",
    "terrain-props": "Props & Accessories",
    "accessories": "Accessories",
}

PARENT_DISPLAY_NAMES = {
    "wargaming-tabletop": "Wargaming & Tabletop",
    "scale-model-kits": "Scale Model Kits",
    "anime-fantasy-figures": "Anime & Fantasy Figures",
    "accessories": "Accessories",
    "diorama-terrain": "Diorama & Terrain",
}


def _describe_subject(title, category_handle):
    """Generate a natural 2-3 sentence opener tailored to the product."""
    t = title.lower()
    cat = category_handle

    # Detect subject matter for tailored descriptions
    if any(w in t for w in ["garage", "mechanic", "repair", "workshop"]):
        return (f"A finely detailed miniature depicting a garage workshop scene. "
                f"Ideal for automotive diorama builders looking to add life and authenticity "
                f"to their scale displays.")
    if any(w in t for w in ["fishing", "outdoor"]):
        return (f"A charming miniature figure capturing an outdoor fishing scene. "
                f"Great for diorama builders and model railway enthusiasts who want "
                f"natural, lived-in details.")
    if any(w in t for w in ["golf", "sport"]):
        return (f"A detailed miniature figure in a sporting pose, perfect for "
                f"scene-building and display dioramas. Adds a touch of realism "
                f"to any leisure-themed layout.")
    if any(w in t for w in ["band", "singer", "music"]):
        return (f"A lively miniature figure capturing a musical performance. "
                f"Perfect for adding character to diorama street scenes "
                f"or creative display pieces.")
    if any(w in t for w in ["motorcycle", "biker", "helmet"]):
        return (f"A dynamic miniature figure with motorcycle-themed detailing. "
                f"A great accent piece for automotive dioramas "
                f"and scale model displays.")
    if any(w in t for w in ["robot", "mech", "sci-fi", "science fiction"]):
        return (f"A striking sci-fi miniature with crisp mechanical detailing. "
                f"Perfect for painters and collectors who love futuristic themes "
                f"and display-quality figures.")
    if any(w in t for w in ["warrior", "knight", "samurai", "viking"]):
        return (f"A commanding warrior figure with sharp detail on armour and weaponry. "
                f"An excellent subject for display painting or tabletop gaming.")
    if "bust" in t or cat == "busts-portraits":
        return (f"A detailed resin bust capturing expressive facial features and texture. "
                f"An ideal canvas for portrait-painting practice "
                f"or display-cabinet centrepieces.")
    if any(w in t for w in ["tank", "panzer", "vehicle", "military"]):
        return (f"A precision-cast resin model kit of a military vehicle. "
                f"Features accurate panel lines and hardware detailing "
                f"for scale-model enthusiasts.")
    if any(w in t for w in ["dragon", "monster", "creature"]):
        return (f"An imposing creature miniature with dynamic posing and rich surface texture. "
                f"A rewarding project for experienced painters "
                f"and a striking display piece.")
    if any(w in t for w in ["anime", "manga", "waifu"]):
        return (f"A collector-grade anime-style resin figure with flowing lines "
                f"and expressive detail. Perfect for figure painters "
                f"and anime display shelves.")
    if any(w in t for w in ["terrain", "scenery", "building", "ruin"]):
        return (f"Detailed terrain scenery piece to bring your tabletop or diorama to life. "
                f"Works with a wide range of miniature scales "
                f"and gaming systems.")
    # Generic fallback
    return (f"A finely detailed resin miniature figure — perfect for diorama builders, "
            f"painters, and collectors. Rich surface detail rewards careful painting "
            f"and looks excellent on display.")


def generate_description(title, category_handle, scale):
    """Generate rich 3-section HTML product description (<200 words)."""
    cat_name = CATEGORY_DISPLAY_NAMES.get(category_handle, "Props & Accessories")
    parent = PARENT_COLLECTIONS.get(category_handle)
    product_type = PARENT_DISPLAY_NAMES.get(parent, "Diorama & Terrain") if parent else "Diorama & Terrain"

    opener = _describe_subject(title, category_handle)

    return f"""<h3>{product_type} — {cat_name}</h3>
<p>{opener}</p>

<h4>What's Included</h4>
<ul>
  <li>Material: High-quality resin</li>
  <li>Scale: {scale}</li>
  <li>Condition: Unpainted, unassembled — requires modelling skills</li>
  <li>Parts: Multi-part kit (assembly required)</li>
  <li><strong>Not included:</strong> Paints, glue, tools, or display base (unless stated)</li>
</ul>

<h4>Painting &amp; Assembly Tips</h4>
<ul>
  <li>Wash all parts in warm soapy water before priming to remove mould-release residue</li>
  <li>Use a resin-compatible primer (grey or white) for best paint adhesion</li>
  <li>Acrylic hobby paints (Vallejo, Citadel, AK Interactive) work best on resin</li>
  <li>Dry-fit parts before gluing — super glue (CA) is recommended for resin</li>
  <li>Fine-grit sanding (400–600) smooths any mould lines</li>
</ul>

<h4>Shipping</h4>
<p>Free worldwide shipping. 5–7 day delivery to USA &amp; Europe, 7–14 days rest of world. All orders include tracking.</p>"""


def generate_seo_title(title):
    """Generate SEO page title."""
    return f"{title} | CastForge"


def generate_seo_description(title):
    """Generate SEO meta description."""
    return f"Shop {title} at CastForge. High-detail resin model kit. Free worldwide shipping. 5-7 day delivery."
