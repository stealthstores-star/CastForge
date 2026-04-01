"""
CastForge SEO Module
Generates SEO titles, meta descriptions, URL handles, image alt text,
and auto-tags for every product.
"""

import re

from categorizer import PARENT_COLLECTIONS, PARENT_DISPLAY_NAMES, CATEGORY_DISPLAY_NAMES

# ═══════════════════════════════════════════════════════════════
# SCALE DETECTION
# ═══════════════════════════════════════════════════════════════

_SCALE_FRACTION = re.compile(r"\b1[:/](\d{1,3})\b")
_SCALE_MM = re.compile(r"\b(\d{2,3})\s*mm\b", re.IGNORECASE)


def _detect_scale(title):
    """Return normalised scale string or empty."""
    m = _SCALE_FRACTION.search(title)
    if m:
        return f"1/{m.group(1)}"
    m = _SCALE_MM.search(title)
    if m:
        return f"{m.group(1)}mm"
    return ""


# ═══════════════════════════════════════════════════════════════
# PRODUCT TYPE WORD
# ═══════════════════════════════════════════════════════════════

_TYPE_MAP = {
    "busts-portraits": "Bust",
    "terrain-bases-plinths": "Terrain Base",
    "terrain-scenery": "Terrain Piece",
    "terrain-buildings-ruins": "Terrain Kit",
    "terrain-natural": "Terrain Piece",
    "terrain-props": "Accessory Set",
    "wargaming-infantry": "Miniature",
    "wargaming-vehicles-mechs": "Vehicle Kit",
    "wargaming-monsters-creatures": "Creature Figure",
    "wargaming-heroes-characters": "Character Figure",
    "wargaming-army-bundles": "Army Set",
    "scale-military-vehicles": "Model Kit",
    "scale-aircraft": "Model Kit",
    "scale-ships-naval": "Model Kit",
    "scale-cars-motorcycles": "Model Kit",
    "anime-characters": "Figure",
    "fantasy-warriors": "Figure",
    "scifi-figures": "Figure",
    "uncategorized": "Figure",
}


def _type_word(category_handle):
    return _TYPE_MAP.get(category_handle, "Figure")


# ═══════════════════════════════════════════════════════════════
# 1. SEO TITLE  (<60 chars)
#    Format: [Product Description] [Scale] Resin [Type] | CastForge
# ═══════════════════════════════════════════════════════════════

def seo_title(title, category_handle):
    """Generate SEO title under 60 characters."""
    scale = _detect_scale(title)
    type_word = _type_word(category_handle)
    suffix = f" | CastForge"

    # Strip scale from the descriptive part (we re-add it in proper position)
    desc = _SCALE_FRACTION.sub("", title)
    desc = _SCALE_MM.sub("", desc)
    # Clean junk words that waste SEO chars
    desc = re.sub(r"\b(?:Resin|Model|Kit|Diorama|Miniature|Figure|Miniatura|Minifigures?|Minifigura|Props?|Creative|Photography|Display|Collection|Decoration|Diy|Craft|Toys?|Collectib\w*|Scenes?|Garage|Handmade|Painted|Sand\s*Table|Micro\s*landscape|Arquitectura|Mini)\b", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\s{2,}", " ", desc).strip()
    desc = re.sub(r"^\s*[,\-–—]\s*", "", desc).strip()
    desc = re.sub(r"\s*[,\-–—]\s*$", "", desc).strip()

    # Build: desc + scale + "Resin" + type
    parts = [desc]
    if scale:
        parts.append(scale)
    parts.append(f"Resin {type_word}")
    core = " ".join(p for p in parts if p)

    # Truncate core to fit within 60 chars with suffix
    max_core = 60 - len(suffix)
    if len(core) > max_core:
        core = core[:max_core].rsplit(" ", 1)[0]

    return f"{core}{suffix}"


# ═══════════════════════════════════════════════════════════════
# 2. META DESCRIPTION  (<155 chars)
# ═══════════════════════════════════════════════════════════════

def meta_description(title, category_handle):
    """Generate meta description under 155 characters."""
    scale = _detect_scale(title)
    scale_part = f"{scale} scale " if scale else ""

    # Short product descriptor
    desc = title
    if len(desc) > 60:
        desc = desc[:60].rsplit(" ", 1)[0]

    meta = f"Shop {desc} at CastForge. {scale_part}Resin kit, unpainted & unassembled. Free worldwide shipping, 5-7 day delivery."

    if len(meta) > 155:
        meta = meta[:152].rsplit(" ", 1)[0] + "..."

    return meta


# ═══════════════════════════════════════════════════════════════
# 3. URL HANDLE  (lowercase, hyphens, max 60 chars)
#    Keep scale references, strip other numbers
# ═══════════════════════════════════════════════════════════════

_SCALE_PLACEHOLDER = re.compile(r"(1[:/]\d{1,3}|\d{2,3}\s*mm)", re.IGNORECASE)


_HANDLE_SCALE = re.compile(r"(1[:/]\d{1,3}|\d{2,3}\s*mm)", re.IGNORECASE)
_HANDLE_PLACEHOLDERS = "abcdefghij"


def url_handle(title):
    """Generate clean URL handle from title."""
    t = title.lower()

    # Find and extract all scale references
    scales_found = list(_HANDLE_SCALE.finditer(t))

    # Replace scales with letter-only placeholders (reverse to keep positions)
    replacements = []
    for i, m in enumerate(reversed(scales_found)):
        ph = f"xscalex{_HANDLE_PLACEHOLDERS[i]}x"
        t = t[:m.start()] + f" {ph} " + t[m.end():]
        replacements.append((ph, m.group()))

    # Strip all remaining digits
    t = re.sub(r"\d+", "", t)

    # Restore scale placeholders
    for ph, val in replacements:
        normalised = val.lower().replace(":", "-").replace("/", "-").replace(" ", "")
        t = t.replace(ph, normalised)

    # Replace non-alphanumeric with hyphens
    t = re.sub(r"[^a-z0-9-]", "-", t)
    t = re.sub(r"-{2,}", "-", t)
    t = t.strip("-")

    # Truncate to 60 chars on a word boundary
    if len(t) > 60:
        t = t[:60].rsplit("-", 1)[0]

    return t


# ═══════════════════════════════════════════════════════════════
# 4. IMAGE ALT TEXT
#    Format: [Product title] - [scale] scale resin model kit from CastForge
# ═══════════════════════════════════════════════════════════════

def image_alt_text(title, position=1):
    """Generate image alt text."""
    scale = _detect_scale(title)
    scale_part = f"{scale} scale " if scale else ""
    alt = f"{title} - {scale_part}resin model kit from CastForge"
    if len(alt) > 125:
        alt = alt[:122] + "..."
    if position > 1:
        alt = f"{title[:80]} - Image {position}"
    return alt


# ═══════════════════════════════════════════════════════════════
# 5. AUTO-TAGS
#    Scale, era, type, material + category tags
# ═══════════════════════════════════════════════════════════════

_ERA_KEYWORDS = {
    "medieval": ["medieval", "knight", "crusader", "castle", "templar", "viking", "saxon", "norman"],
    "ancient": ["roman", "greek", "spartan", "gladiator", "centurion", "legionary", "ancient", "egyptian", "persian"],
    "ww2": ["ww2", "wwii", "world war", "panzer", "tiger", "sherman", "t-34", "spitfire", "messerschmitt", "1940", "1944", "normandy"],
    "ww1": ["ww1", "wwi", "trench", "1914", "1918"],
    "napoleonic": ["napoleon", "napoleonic", "hussar", "dragoon", "grenadier", "waterloo"],
    "modern": ["modern", "special forces", "swat", "operator", "tactical"],
    "fantasy": ["fantasy", "dragon", "wizard", "mage", "elf", "dwarf", "orc", "demon", "undead", "skeleton", "barbarian", "dark fantasy"],
    "sci-fi": ["sci-fi", "scifi", "cyberpunk", "robot", "mech", "alien", "space", "futuristic", "android"],
    "historical": ["samurai", "pirate", "cowboy", "civil war", "musketeer", "zulu"],
    "anime": ["anime", "manga", "waifu", "chibi"],
}

_TYPE_KEYWORDS = {
    "miniature": ["miniature", "miniatures", "mini", "figure", "figures"],
    "bust": ["bust", "portrait", "torso"],
    "terrain": ["terrain", "scenery", "base", "plinth", "ruin", "building"],
    "vehicle": ["tank", "vehicle", "aircraft", "ship", "car", "motorcycle", "truck", "mech"],
    "diorama": ["diorama", "scene", "scenes", "display", "garage"],
    "bundle": ["bundle", "set", "pack", "army", "lot"],
}


def auto_tags(title, category_handle):
    """Generate product tags from title and category."""
    t = title.lower()
    tags = set()

    # Always add "new" for smart collection
    tags.add("new")

    # Material
    tags.add("resin")

    # Scale tags
    m = _SCALE_FRACTION.search(title)
    if m:
        tags.add(f"1/{m.group(1)}")
        tags.add(f"1:{m.group(1)}")  # alternate format
    m = _SCALE_MM.search(title)
    if m:
        tags.add(f"{m.group(1)}mm")

    # Era tags
    for era, keywords in _ERA_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            tags.add(era)

    # Type tags
    for type_tag, keywords in _TYPE_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            tags.add(type_tag)

    # Category-derived tags
    cat_name = CATEGORY_DISPLAY_NAMES.get(category_handle, "")
    if cat_name:
        tags.add(cat_name.lower())

    parent = PARENT_COLLECTIONS.get(category_handle)
    parent_name = PARENT_DISPLAY_NAMES.get(parent, "")
    if parent_name:
        tags.add(parent_name.lower())

    # Sort for consistency
    return sorted(tags)


# ═══════════════════════════════════════════════════════════════
# ALL-IN-ONE HELPER
# ═══════════════════════════════════════════════════════════════

def generate_seo(title, category_handle):
    """Generate all SEO fields for a product. Returns a dict."""
    return {
        "seo_title": seo_title(title, category_handle),
        "seo_description": meta_description(title, category_handle),
        "handle": url_handle(title),
        "image_alt": image_alt_text(title),
        "tags": auto_tags(title, category_handle),
    }
