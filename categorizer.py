"""
CastForge Product Categorizer
Keyword-scoring engine that assigns products to the correct collection.
"""

import re

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
            "1/24", "1/18",
        ],
        "negative": ["tank", "aircraft", "ship", "bust", "infantry"],
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
        ],
        "negative": ["vehicle", "terrain", "tank", "aircraft", "bust"],
    },
    "scifi-figures": {
        "keywords": [
            "sci-fi figure", "cyberpunk", "robot figure", "android", "cyborg",
            "mecha pilot", "power armor", "alien figure", "post-apocalyptic",
        ],
        "negative": ["tank", "terrain", "bust", "fantasy"],
    },
    "busts-portraits": {
        "keywords": [
            "bust", "portrait", "head", "torso", "1/10 bust", "1/12 bust",
            "display bust", "pedestal", "museum piece",
        ],
        "negative": ["infantry", "vehicle", "terrain", "army", "troops"],
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
            "diorama", "scene", "scenes", "garage", "repair", "workshop",
            "accessories", "decoration", "display",
        ],
        "negative": ["bust", "infantry", "vehicle"],
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
    "display collection decoration", "collection decoration",
    "action figure collectib", "creative photography", "creative display",
    "micro creative", "props creative", "model props",
    "3d resin printing", "3d printing", "hand painted", "handpainted",
    "diy craft toys", "diy craft", "garage scenes", "garage scene",
    "scene matching", "anime figure", "free shipping", "hot sale",
    "new arrival", "best quality", "high quality", "top quality",
    "brand new", "factory direct", "limited time", "flash sale",
    "big sale", "fast delivery", "in stock", "us warehouse",
    # Single words
    "wholesale", "dropship", "aliexpress", "cheap",
    "collectible", "collectib", "miniatura", "minifigura",
    "minifigures", "minifigure",
]

# Sort longest first for greedy matching
ALIEXPRESS_JUNK.sort(key=len, reverse=True)

JUNK_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(j) for j in ALIEXPRESS_JUNK) + r")\w*\b",
    re.IGNORECASE,
)

DISCOUNT_PATTERN = re.compile(r"\d+%\s*off", re.IGNORECASE)
MULTI_SPACE = re.compile(r"\s{2,}")
SCALE_PATTERN = re.compile(r"(1[:/]\d{1,3})", re.IGNORECASE)
SCALE_MM_PATTERN = re.compile(r"(\d{2,3}\s*mm)", re.IGNORECASE)

MAX_TITLE_LENGTH = 60

# Map category → type suffix for short titles
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
    "uncategorized": "Resin Figure",
}


def clean_title(title, category_handle="uncategorized"):
    """
    Remove AliExpress spam, title-case, and limit to 60 chars.
    Format: descriptive name + scale + Resin Figure/Kit/Bust.
    """
    t = JUNK_PATTERN.sub("", title)
    t = DISCOUNT_PATTERN.sub("", t)

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

    # Strip existing scale and generic type words from desc
    desc = t
    desc = SCALE_PATTERN.sub("", desc)
    desc = SCALE_MM_PATTERN.sub("", desc)
    desc = re.sub(r"\b(?:Resin|Model|Kit|Figure|Figures|Bust|Set|Scale|Diorama|"
                  r"Miniature|Miniatures|Sand|Table|Scene|Scence|Micro|"
                  r"Mini|Landscape|Arquitectura|Wt\d*|Pcs?|Handmade|Diy|"
                  r"Painted|Photography|Tiny|Static|Piece)\b",
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

    # Enforce 60-char limit — truncate desc at word boundary keeping scale+suffix
    if len(t) > MAX_TITLE_LENGTH:
        suffix_part = f" {scale} {type_suffix}" if scale else f" {type_suffix}"
        max_desc_len = MAX_TITLE_LENGTH - len(suffix_part)
        if max_desc_len > 5:
            desc = desc[:max_desc_len].rsplit(" ", 1)[0].rstrip(" ,—-–")
            t = f"{desc}{suffix_part}"
        else:
            t = t[:MAX_TITLE_LENGTH].rsplit(" ", 1)[0].rstrip(" ,—-–")

    return t


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
        return "uncategorized", best_score, None

    parent = PARENT_COLLECTIONS.get(best)
    return best, best_score, parent


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
    "uncategorized": "Collectible",
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
    cat_name = CATEGORY_DISPLAY_NAMES.get(category_handle, "Collectible")
    parent = PARENT_COLLECTIONS.get(category_handle)
    product_type = PARENT_DISPLAY_NAMES.get(parent, "Collectible") if parent else "Collectible"

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
