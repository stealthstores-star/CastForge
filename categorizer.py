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

CATEGORIES = {
    # ── Wargaming ──
    "wargaming-infantry": {
        "keywords": [
            "infantry", "troops", "soldiers", "squad", "regiment", "platoon",
            "guardsmen", "warriors", "militia", "marines", "battle sisters",
            "skeletons", "zombies", "undead", "orc boyz", "goblins", "elves",
            "dwarf warriors", "sci-fi troops", "clone",
        ],
        "negative": ["vehicle", "bust", "terrain", "building", "base", "plinth"],
    },
    "wargaming-vehicles-mechs": {
        "keywords": [
            "mech", "walker", "titan", "dreadnought", "warjack",
            "battle suit", "robot", "war machine", "tank miniature",
            "hover tank", "grav tank", "sentinel", "stompa", "gorkanaut",
        ],
        "negative": ["bust", "infantry", "troops", "terrain"],
    },
    "wargaming-monsters-creatures": {
        "keywords": [
            "monster", "creature", "beast", "demon", "daemon",
            "dragon miniature", "hydra", "wyrm", "wyvern", "giant", "troll",
            "ogre", "minotaur", "spider", "brood", "swarm", "cthulhu",
            "eldritch", "xenomorph",
        ],
        "negative": ["bust", "vehicle", "terrain", "tank", "aircraft"],
    },
    "wargaming-heroes-characters": {
        "keywords": [
            "hero", "commander", "captain", "general", "warlord",
            "champion", "leader", "character", "wizard", "sorcerer", "mage",
            "psyker", "warlock", "paladin", "lord", "king", "queen",
            "assassin", "rogue", "ranger", "commissar", "inquisitor",
            "chaplain", "necromancer",
        ],
        "negative": ["vehicle", "terrain", "bust", "tank", "aircraft"],
    },
    "wargaming-army-bundles": {
        "keywords": [
            "army", "bundle", "starter", "lot", "set of", "warband",
            "regiment set", "army box", "kill team", "patrol",
            "10pc", "20pc", "5pc", "mega bundle",
        ],
        "negative": ["bust", "terrain", "single"],
    },

    # ── Scale Models ──
    "scale-military-vehicles": {
        "keywords": [
            "1/72", "1/35", "1/48", "1/76", "1/144", "tank", "panzer",
            "tiger", "sherman", "t-34", "leopard", "abrams", "halftrack",
            "armored car", "artillery", "howitzer", "ww2 vehicle", "wwii",
            "military model", "afv", "panther", "stug", "sdkfz",
        ],
        "negative": ["bust", "figure", "miniature figure", "diorama figure",
                      "aircraft", "ship", "plane", "boat"],
    },
    "scale-aircraft": {
        "keywords": [
            "aircraft", "airplane", "plane", "fighter", "bomber", "spitfire",
            "mustang", "p-51", "messerschmitt", "zero", "corsair", "hurricane",
            "lancaster", "jet fighter", "f-16", "helicopter", "apache", "aviation",
        ],
        "negative": ["tank", "ship", "bust", "infantry", "car"],
    },
    "scale-ships-naval": {
        "keywords": [
            "ship", "battleship", "destroyer", "cruiser", "carrier", "submarine",
            "u-boat", "frigate", "naval", "warship", "bismarck", "yamato",
            "boat model",
        ],
        "negative": ["tank", "aircraft", "bust", "plane", "car"],
    },
    "scale-cars-motorcycles": {
        "keywords": [
            "car model", "race car", "rally", "f1", "formula", "motorcycle",
            "motorbike", "truck", "muscle car", "classic car", "sports car",
            "1/24", "1/18", "car", "automobile", "vehicle model",
            "hot rod", "drag car", "racing", "gt", "supercar",
        ],
        "negative": ["tank", "aircraft", "ship", "bust", "infantry",
                      "armored car"],
    },

    # ── Anime & Fantasy Figures ──
    "anime-characters": {
        "keywords": [
            "anime", "manga", "waifu", "bishoujo", "one piece",
            "dragon ball", "demon slayer", "jujutsu", "my hero academia",
            "evangelion", "sailor moon", "fate", "kawaii", "otaku",
        ],
        "negative": ["tank", "vehicle", "terrain", "building"],
    },
    "fantasy-warriors": {
        "keywords": [
            "fantasy figure", "barbarian", "viking", "gladiator", "samurai",
            "knight figure", "crusader", "elven warrior", "dark elf",
            "female warrior", "amazon", "valkyrie", "berserker", "conan",
            "warrior", "knight", "soldier", "archer", "swordsman",
            "spartan", "centurion", "legionary", "roman soldier",
            "medieval", "templar", "musketeer", "pirate figure",
            "notre dame", "statue", "goddess", "angel figure",
            "figure colorless", "self-assembled",
            "resin model kits figure", "resin figure",
        ],
        "negative": ["vehicle", "terrain", "tank", "aircraft",
                      "1/64", "1/100", "1/144", "garage", "diorama scene"],
    },
    "scifi-figures": {
        "keywords": [
            "sci-fi figure", "cyberpunk", "robot figure", "android", "cyborg",
            "mecha pilot", "power armor", "alien figure", "post-apocalyptic",
            "science fiction", "sci fi",
        ],
        "negative": ["tank", "terrain", "fantasy"],
    },
    "busts-portraits": {
        "keywords": [
            "bust", "portrait", "torso", "1/10 bust", "1/12 bust",
            "display bust", "pedestal", "museum piece",
            "resin bust", "model bust",
            "200mm", "150mm", "100mm", "90mm", "75mm", "54mm",
            "1/10", "1/9", "1/8", "1/7", "1/6",
            "head sculpt", "face", "half body",
        ],
        "negative": ["infantry", "vehicle", "terrain", "army", "troops",
                      "1/64", "1/35", "1/72", "1/48", "1/100", "1/144",
                      "garage", "diorama scene"],
    },

    # ── Diorama & Terrain ──
    "terrain-bases-plinths": {
        "keywords": [
            "base", "plinth", "display base", "scenic base", "round base",
            "movement tray", "magnetic base",
        ],
        "negative": ["bust", "figure", "infantry", "vehicle"],
    },
    "terrain-scenery": {
        "keywords": [
            "scenery", "scatter terrain", "barricade", "wall", "fence", "crate",
            "barrel", "objective marker", "campfire", "bridge",
        ],
        "negative": ["bust", "figure", "vehicle", "infantry"],
    },
    "terrain-buildings-ruins": {
        "keywords": [
            "building", "ruin", "ruins", "tower", "castle", "church",
            "temple", "house", "fortress", "bunker", "watchtower", "gothic",
        ],
        "negative": ["bust", "figure", "vehicle", "infantry"],
    },
    "terrain-natural": {
        "keywords": [
            "tree", "forest", "rock", "boulder", "cliff", "hill", "river",
            "mushroom", "crystal", "cave", "swamp", "bush",
        ],
        "negative": ["bust", "figure", "vehicle", "infantry", "building"],
    },
    "terrain-props": {
        "keywords": [
            "prop", "accessory", "weapon rack", "treasure chest",
            "throne", "altar", "portal", "tombstone", "grave", "cart",
            "garage", "repair", "workshop",
            "1/64 diorama", "diorama set", "scene prop",
        ],
        "negative": ["bust", "infantry", "vehicle", "figure", "warrior",
                      "knight", "soldier", "75mm", "90mm", "200mm", "54mm",
                      "1/10", "1/35"],
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

ALIEXPRESS_JUNK.sort(key=len, reverse=True)

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
}

# AI title cache
_AI_TITLE_CACHE_FILE = Path("ai_title_cache.json")


def _load_title_cache():
    if _AI_TITLE_CACHE_FILE.exists():
        return json.loads(_AI_TITLE_CACHE_FILE.read_text())
    return {}


def _save_title_cache(cache):
    _AI_TITLE_CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False))


def clean_title(title, category_handle="terrain-props"):
    """
    Remove AliExpress spam, title-case, and limit to 60 chars.
    Format: descriptive name + scale + Resin Figure/Kit/Bust.
    """
    t = JUNK_PATTERN.sub("", title)
    t = DISCOUNT_PATTERN.sub("", t)

    # Strip catalog codes (A-757, Td-3622, Hong-06, Jk12, etc.)
    # but preserve military designations (F16, T34, WW2, etc.)
    def _strip_catalog(m):
        code = m.group().upper()
        return m.group() if code in _MILITARY_DESIGNATIONS else ""
    t = CATALOG_CODE_PATTERN.sub(_strip_catalog, t)

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
        "You are naming products for a premium resin miniature store. "
        "Based on this AliExpress title, write a compelling product name "
        "that a hobbyist would search for. Be SPECIFIC about what the figure "
        "depicts — if it's a knight say what kind of knight, if it's a soldier "
        "say what era and role, if it's a fantasy creature describe it. "
        "Include the scale. Under 50 characters. "
        "Do NOT use generic words like standing, figure, portrait, character, "
        "model, assembly, resin, kit, DIY, colorless, self-assembled. "
        "Examples of GOOD titles: "
        "Viking Berserker with Axe 75mm, "
        "WW2 German Panzer Commander 1/35, "
        "Japanese Schoolgirl Anime 1/35, "
        "Dwarf King on Throne 54mm, "
        "Roman Legionnaire Charging 1/10 Bust, "
        "Dragon Perched on Skull 200mm. "
        "Respond with ONLY the product name, nothing else."
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
                "text": f"{prompt}\n\nOriginal title: {raw}",
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
    Score a product against all categories. Returns (best_handle, score, parent_handle).
    """
    text = f"{title} {description}".lower()
    scores = {}

    for handle, data in CATEGORIES.items():
        score = 0
        for kw in data["keywords"]:
            if kw in text:
                # Title match = +3, description-only = +1
                if kw in title.lower():
                    score += 3
                else:
                    score += 1
        for neg in data.get("negative", []):
            if neg in text:
                score -= 5
        scores[handle] = max(score, 0)

    best = max(scores, key=scores.get)
    best_score = scores[best]

    if best_score < 2:
        # Use Claude AI for accurate categorization
        return _ai_categorize(title)

    parent = PARENT_COLLECTIONS.get(best)
    return best, best_score, parent


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

_AI_PROMPT = (
    "Categorize this resin model into exactly one of these categories: "
    "Infantry & Troops, Vehicles & Mechs, Monsters & Creatures, "
    "Heroes & Characters, Army Bundles, Military Vehicles, Aircraft, "
    "Ships & Naval, Cars & Motorcycles, Anime Characters, Fantasy Warriors, "
    "Sci-Fi Figures, Busts & Portraits, Bases & Plinths, Scenery Pieces, "
    "Buildings & Ruins, Natural Elements, Props & Accessories. "
    "Product title: {title}. "
    "Respond with ONLY the category name, nothing else."
)


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
    # resolved by ai_categorize_batch
    return "terrain-props", 0, "diorama-terrain"


def ai_categorize_batch(products, api_key):
    """
    Batch-categorize products that scored < 2 using Claude API.
    Call this from the pipeline AFTER initial categorize() pass.
    Processes 10 at a time, caches results.
    """
    import requests as req

    cache = _load_ai_cache()
    uncategorized = []
    cached_hits = 0

    for p in products:
        title = p.get("_raw_title", p.get("title", ""))
        if title in cache:
            # Apply cached AI category — but validate it first
            handle = _validate_ai_category(cache[title], title)
            if handle != cache[title]:
                cache[title] = handle  # update cache with corrected value
            parent = PARENT_COLLECTIONS.get(handle, "diorama-terrain")
            p["category_handle"] = handle
            p["parent_handle"] = parent
            p["product_type"] = PARENT_DISPLAY_NAMES.get(parent, "Diorama & Terrain")
            cached_hits += 1
        else:
            uncategorized.append((p, title))

    if cached_hits:
        print(f"  AI cache: applied {cached_hits} cached categories")

    if not uncategorized:
        return

    print(f"  AI categorizing {len(uncategorized)} products (batches of 10)...")

    batch_size = 10
    categorized = 0

    for i in range(0, len(uncategorized), batch_size):
        batch = uncategorized[i:i + batch_size]

        for product, title in batch:
            if title in cache:
                handle = cache[title]
            else:
                handle = _call_claude_categorize(title, api_key)
                # Validate: catch absurd mismatches
                handle = _validate_ai_category(handle, title)
                cache[title] = handle
                categorized += 1

            parent = PARENT_COLLECTIONS.get(handle, "diorama-terrain")
            product["category_handle"] = handle
            product["parent_handle"] = parent

            # Update product_type display name
            parent_name = PARENT_DISPLAY_NAMES.get(parent, "Diorama & Terrain")
            product["product_type"] = parent_name

        _save_ai_cache(cache)

        done = min(i + batch_size, len(uncategorized))
        print(f"    [{done}/{len(uncategorized)}] categorized")

        # Small delay between batches
        if i + batch_size < len(uncategorized):
            import time
            time.sleep(0.5)

    print(f"  AI categorized {categorized} products ({len(cache)} cached total)")


def _call_claude_categorize(title, api_key):
    """Call Claude API to categorize a single product title."""
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
                    "content": _AI_PROMPT.format(title=title),
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

    # If API fails, fall back to Props & Accessories
    return "terrain-props"


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
}

PARENT_DISPLAY_NAMES = {
    "wargaming-tabletop": "Wargaming & Tabletop",
    "scale-model-kits": "Scale Model Kits",
    "anime-fantasy-figures": "Anime & Fantasy Figures",
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
