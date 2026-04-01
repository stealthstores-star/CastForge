"""
CastForge Compliance Module
Scans product titles and images for trademark, copyright, and IP violations.
Runs BEFORE upload — nothing goes to Shopify without passing compliance.
"""

import base64
import csv
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import requests

import config

# ═══════════════════════════════════════════════════════════════
# BLOCKLISTS
# ═══════════════════════════════════════════════════════════════

# TIER 1 — HARD BLOCK (remove product entirely)
LICENSED_CHARACTERS_BLOCK = [
    # Superheroes
    "batman", "superman", "spider-man", "spiderman", "iron man", "ironman",
    "wolverine", "hulk", "thor", "captain america", "black widow",
    "deadpool", "venom", "thanos", "joker", "harley quinn",
    "wonder woman", "aquaman", "flash",
    # DC/Marvel general
    "marvel", "dc comics", "avengers", "justice league", "x-men",
    # Star Wars
    "star wars", "darth vader", "yoda", "mandalorian", "boba fett",
    "stormtrooper", "jedi", "sith", "lightsaber", "baby yoda", "grogu",
    # Disney / Pixar
    "disney", "pixar", "mickey mouse", "frozen", "elsa",
    # James Bond
    "007", "james bond",
    # Harry Potter
    "harry potter", "hogwarts", "dumbledore", "voldemort",
    # Lord of the Rings (if clearly branded)
    "games workshop lotr", "gw lord of the rings",
    # Pokemon
    "pokemon", "pikachu", "charizard",
    # Specific anime (if the sculpt IS the character)
    "naruto uzumaki", "goku", "luffy", "eren yeager", "tanjiro",
    # Video games
    "master chief", "halo", "zelda", "link", "mario", "sonic",
    "kratos", "god of war", "elden ring", "dark souls branded",
    "overwatch", "league of legends",
    # Other major IP
    "transformers",
]

# TIER 2 — STRIP BRAND, KEEP PRODUCT
MINIATURE_BRANDS_STRIP = [
    "gk miniatures", "gk model", "gk resin",
    "games workshop", "citadel miniatures", "forge world",
    "warhammer 40k", "warhammer 40,000", "warhammer", "age of sigmar",
    "kill team", "necromunda", "blood bowl", "underworlds",
    "kingdom death monster", "kingdom death", "kdm", "kd monster", "dead kingdom",
    "corvus belli", "infinity the game", "infinity n4",
    "ariadna", "panoceania", "haqqislam", "yu jing",
    "nomads", "combined army", "tohaa", "aleph",
    "shasvastii", "jsa",
    "privateer press", "warmachine", "hordes",
    "khador", "cygnar", "menoth", "cryx",
    "skorne", "trollbloods", "circle orboros",
    "para bellum", "conquest", "the last argument of kings",
    "avatars of war", "avatar of war",
    "dark sword miniatures", "dark sword",
    "reaper miniatures", "reaper minis",
    "wizkids", "nolzur",
    "moonstone the game", "moonstone",
    "gamezone miniatures", "gamezone",
    "rackham", "confrontation",
    "michael kontraros", "mk collectibles",
    "scale 75", "scale75",
    "nocturna models", "nocturna",
    "nutsplanet", "nuts planet",
    "andrea miniatures", "andrea press",
    "pegaso models", "pegaso",
    "alexandros models",
    "romeo models",
    "el viejo dragon", "evd",
    "young miniatures",
    "life miniatures",
    "alpine miniatures",
    "mantis miniatures",
    "bravo 6", "bravo6",
    "stalingrad miniatures",
    "masterbox", "master box",
    "miniart", "mini art",
    "verlinden",
    "legend productions",
    "evolution miniatures",
    "mantic games", "mantic",
    "frostgrave",
    "northstar", "north star military figures",
    "perry miniatures", "perry twins",
    "warlord games", "bolt action",
    "battlefront", "flames of war",
    "wyrd", "malifaux",
    "atomic mass games", "star wars legion",
    "fantasy flight", "ffg",
    "paizo",
    "wizards of the coast", "wotc",
    "hasbro",
    "cmon", "cool mini or not",
    "zombicide",
    "steamforged", "guild ball",
    "catalyst game labs", "battletech",
    # Short brand abbreviations (word-boundary matched)
    "gk", "gw", "kd",
]

# Privateer Press character names that must be stripped
PP_CHARACTER_NAMES = [
    "skarre", "deneghra", "asphyxious", "gaspy",
    "caine", "stryker", "haley", "siege",
    "kreoss", "severius", "reznik", "feora",
    "irusk", "sorscha", "butcher", "vlad",
    "lylyth", "vayl", "absylonia", "thagrosh",
    "madrak", "grissel", "borka", "grim",
    "krueger", "baldur", "morvahna", "kaya",
    "mordikaar", "makeda", "xerxis", "zaal",
]

SCULPTOR_NAMES_STRIP = [
    "michael kontraros", "raul garcia latorre", "jason wiebe",
    "jacques alexandre gillois", "pedro fernandez ramos",
    "jose david cabrera", "juan jose baena", "kirill kanaev",
    "romain van den bogaert", "luca coltelli",
    "sergio calvo", "alfonso giraldes", "banshee",
    "heriberto martinez valle", "yeong jin jeon",
    "jin young song", "mj kim",
]

# TIER 3 — Catalog number patterns
CATALOG_NUMBER_PATTERNS = [
    r"^[A-Z]-?\d{3}\b",          # X-103, X-124
    r"^\d{5}\b",                  # 28220, 28306, 35607
    r"^Ref\.\s*[A-Z]\d+",        # Ref. R55
    r"\b\d{4,5}[A-Z]?\b",        # 5-digit catalog numbers mid-title
    r"^[A-Z]{2,3}-\d{3,4}\b",    # GK-1234, MK-567
]
# Scale patterns to PRESERVE
SCALE_PATTERN = re.compile(
    r"\b(?:1[:/]\d{1,3}|\d{2,3}\s*mm)\b", re.IGNORECASE
)

# TIER 4 — Real people
REAL_PEOPLE_STRIP = [
    "brad pitt", "sean connery", "arnold schwarzenegger",
    "keanu reeves", "johnny depp",
    "queen elizabeth",
    "putin", "trump", "biden", "xi jinping",
]

COPYRIGHTED_FILMS_STRIP = [
    "kingdom of heaven",
    "saving private ryan",
    "band of brothers",
    "black hawk down",
    "braveheart",
    "the pacific",
    "dunkirk",
    "hacksaw ridge",
]
# Context-dependent film names (only block when paired with indicators)
CONTEXT_FILMS = {
    "fury": ["brad pitt", "film", "movie", "tank crew"],
    "300": ["film", "movie", "leonidas 300", "spartan 300"],
    "gladiator": ["film", "movie", "russell", "maximus"],
    "1917": ["film", "movie"],
}

# TIER 5 — Game-specific terms
GAME_SPECIFIC_TERMS = [
    # Warhammer 40K
    "space marine", "primaris", "intercessor", "hellblaster",
    "tyranid", "necron", "eldar", "craftworld",
    "aeldari", "drukhari", "genestealer", "chaos space marine",
    "death guard", "thousand sons", "world eater", "emperor's children",
    "imperial guard", "astra militarum", "adeptus mechanicus",
    "sisters of battle", "adepta sororitas", "custodes", "grey knight",
    "blood angel", "dark angel", "space wolf", "ultramarine",
    "imperial fist", "iron hand", "raven guard", "salamander",
    "deathwatch", "black templar",
    # Age of Sigmar
    "stormcast", "nighthaunt", "ossiarch", "lumineth",
    "seraphon", "sylvaneth", "fyreslayer", "kharadron",
    "idoneth", "daughters of khaine", "hedonite",
    "slaanesh", "nurgle", "tzeentch", "khorne",
    "skaven", "gloomspite", "ogor", "sons of behemat",
    "flesh-eater", "soulblight",
    # Kingdom Death specific
    "lantern year", "showdown", "hunt phase",
    "flower knight", "lion knight", "dragon king",
    "watcher", "gold smoke knight",
    # Privateer Press specific
    "warcaster", "warjack", "warbeast",
]

# Junk terms to always strip
JUNK_TERMS = [
    "aliexpress", "dropship", "wholesale", "free shipping",
    "model kit resin kit", "resin kit resin kit",
    "model kit", "resin kit",
    "the film", "the movie",
    "wargame",
]

# ═══════════════════════════════════════════════════════════════
# CATEGORY DETECTION (for title enrichment)
# ═══════════════════════════════════════════════════════════════

CATEGORY_KEYWORDS = {
    "bust": ["bust", "portrait", "1/10", "1/9", "1/8", "1/7", "1/6"],
    "vehicle": ["tank", "panzer", "tiger", "sherman", "t-34", "halftrack",
                 "truck", "jeep", "sdkfz", "vehicle", "car", "motorcycle",
                 "aircraft", "plane", "ship", "boat", "submarine"],
    "terrain": ["terrain", "base", "plinth", "ruin", "building", "scenery",
                "tree", "rock", "bridge", "wall", "fence"],
    "wargaming": ["infantry", "troops", "army", "squad", "soldier",
                   "warrior", "knight", "archer", "28mm", "32mm"],
    "scale_model": ["1/35", "1/72", "1/48", "1/16", "1/24", "1/32"],
    "fantasy": ["dragon", "wizard", "mage", "elf", "dwarf", "orc",
                "demon", "angel", "undead", "skeleton", "vampire",
                "dark fantasy", "fantasy"],
    "scifi": ["sci-fi", "scifi", "alien", "robot", "mech", "cyber",
              "futuristic", "space"],
    "historical": ["wwii", "ww2", "medieval", "roman", "viking", "samurai",
                    "napoleonic", "civil war", "crusader", "ancient",
                    "historical", "greek", "spartan"],
    "anime": ["anime", "manga", "waifu", "chibi"],
}


def detect_category(title):
    """Detect product category from title text."""
    t = title.lower()
    scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        scores[cat] = sum(1 for kw in keywords if kw in t)
    best = max(scores, key=scores.get) if max(scores.values()) > 0 else "fantasy"
    return best


# ═══════════════════════════════════════════════════════════════
# TITLE SCANNER
# ═══════════════════════════════════════════════════════════════

def scan_title(title):
    """
    Scan a product title for compliance issues.
    Returns (cleaned_title, issues, action) where action is 'block', 'clean', or 'ok'.
    """
    issues = []
    original = title
    t = title

    # --- TIER 1: Hard block check ---
    t_lower = t.lower()
    for term in LICENSED_CHARACTERS_BLOCK:
        if re.search(r"\b" + re.escape(term) + r"\b", t_lower):
            issues.append(f"BLOCK: Licensed character/IP '{term}'")
            return original, issues, "block"

    # --- TIER 4: Real people ---
    for person in REAL_PEOPLE_STRIP:
        if re.search(r"\b" + re.escape(person) + r"\b", t_lower):
            issues.append(f"Stripped real person: '{person}'")
            t = re.sub(re.escape(person), "", t, flags=re.IGNORECASE).strip()

    # --- Context-dependent films ---
    t_lower = t.lower()
    for film, triggers in CONTEXT_FILMS.items():
        if re.search(r"\b" + re.escape(film) + r"\b", t_lower):
            if any(tr in t_lower for tr in triggers):
                issues.append(f"Stripped film reference: '{film}' (context match)")
                t = re.sub(r"\b" + re.escape(film) + r"\b", "", t, flags=re.IGNORECASE).strip()

    # --- Straight film names ---
    for film in COPYRIGHTED_FILMS_STRIP:
        if re.search(r"\b" + re.escape(film) + r"\b", t.lower()):
            issues.append(f"Stripped film reference: '{film}'")
            t = re.sub(re.escape(film), "", t, flags=re.IGNORECASE).strip()

    # --- TIER 2: Brand names (longest first to avoid partial matches) ---
    brands_sorted = sorted(MINIATURE_BRANDS_STRIP, key=len, reverse=True)
    for brand in brands_sorted:
        if re.search(r"\b" + re.escape(brand) + r"\b", t.lower()):
            issues.append(f"Stripped brand: '{brand}'")
            t = re.sub(r"\b" + re.escape(brand) + r"\b", "", t, flags=re.IGNORECASE).strip()

    # --- PP Character names ---
    for char in PP_CHARACTER_NAMES:
        if re.search(r"\b" + re.escape(char) + r"\b", t.lower()):
            issues.append(f"Stripped character name: '{char}'")
            t = re.sub(r"\b" + re.escape(char) + r"\b", "", t, flags=re.IGNORECASE).strip()

    # --- Sculptor names ---
    for sculptor in SCULPTOR_NAMES_STRIP:
        if re.search(r"\b" + re.escape(sculptor) + r"\b", t.lower()):
            issues.append(f"Stripped sculptor: '{sculptor}'")
            t = re.sub(re.escape(sculptor), "", t, flags=re.IGNORECASE).strip()

    # --- TIER 5: Game-specific terms ---
    terms_sorted = sorted(GAME_SPECIFIC_TERMS, key=len, reverse=True)
    for term in terms_sorted:
        if re.search(r"\b" + re.escape(term) + r"\b", t.lower()):
            issues.append(f"Stripped game term: '{term}'")
            t = re.sub(r"\b" + re.escape(term) + r"\b", "", t, flags=re.IGNORECASE).strip()

    # --- TIER 3: Catalog numbers (preserve scale numbers) ---
    # Extract and protect scale numbers first
    scales_found = SCALE_PATTERN.findall(t)
    for pat in CATALOG_NUMBER_PATTERNS:
        matches = re.findall(pat, t)
        for m in matches:
            # Don't strip if it's a scale number
            if not SCALE_PATTERN.match(m):
                issues.append(f"Stripped catalog number: '{m}'")
                t = t.replace(m, "", 1).strip()

    # --- Junk terms ---
    for junk in JUNK_TERMS:
        if junk in t.lower():
            t = re.sub(re.escape(junk), "", t, flags=re.IGNORECASE).strip()

    # --- Clean up ---
    # Normalize loose scale fractions: "1 35" → "1/35", "1 72" → "1/72"
    t = re.sub(r"\b1\s+(\d{2,3})\b", r"1/\1", t)

    # Remove orphaned punctuation, double spaces, leading/trailing junk
    t = re.sub(r"\s*[,\-–—]\s*[,\-–—]\s*", " — ", t)
    t = re.sub(r"^\s*[,\-–—]\s*", "", t)
    t = re.sub(r"\s*[,\-–—]\s*$", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    t = re.sub(r"\(\s*\)", "", t).strip()

    # --- Title enrichment if too short ---
    meaningful_words = [w for w in t.split() if len(w) > 2 and not w.isdigit()]
    if len(meaningful_words) < 3:
        t = _enrich_title(t, original, scales_found)
        issues.append("Title enriched (too short after stripping)")

    # Ensure "Resin" appears somewhere
    if "resin" not in t.lower():
        t = _append_resin_suffix(t)

    # Final cleanup
    t = re.sub(r"\s{2,}", " ", t).strip()

    action = "clean" if issues else "ok"
    return t, issues, action


def _enrich_title(stripped, original, scales):
    """Add descriptive words when too much was stripped."""
    cat = detect_category(original)
    scale_str = scales[0] if scales else ""

    enrichments = {
        "bust":        "Resin Display Bust",
        "vehicle":     "Scale Resin Model Kit — Unpainted",
        "terrain":     "Tabletop Terrain Piece — Resin Scenery",
        "wargaming":   "Resin Miniature — Unpainted Kit",
        "scale_model": "Scale Resin Model Kit — Unpainted",
        "fantasy":     "Fantasy Resin Figure — Unpainted Kit",
        "scifi":       "Sci-Fi Resin Figure — Unpainted Kit",
        "historical":  "Historical Resin Figure — Unpainted Collectible",
        "anime":       "Anime Resin Figure — Collector Display",
    }

    suffix = enrichments.get(cat, "Resin Figure — Unpainted Kit")
    parts = [p for p in [stripped, scale_str, suffix] if p]
    return " ".join(parts)


def _append_resin_suffix(title):
    """Append resin descriptor if not already present."""
    cat = detect_category(title)
    suffixes = {
        "bust": " — Resin Display Bust",
        "vehicle": " — Resin Model Kit",
        "terrain": " — Resin Terrain",
        "wargaming": " — Resin Miniature",
        "scale_model": " — Resin Model Kit",
        "fantasy": " — Resin Figure",
        "scifi": " — Resin Figure",
        "historical": " — Resin Figure",
        "anime": " — Resin Figure",
    }
    return title + suffixes.get(cat, " — Resin Kit")


# ═══════════════════════════════════════════════════════════════
# IMAGE SCANNER (Claude Vision)
# ═══════════════════════════════════════════════════════════════

IMAGE_CACHE_FILE = Path("image_scan_cache.json")

VISION_SYSTEM_PROMPT = """You are a copyright compliance scanner for an e-commerce store.
Analyze this product image and report ANY of the following issues:

1. BRAND LOGOS: Any visible brand logos, trademarks, or company names
   (Games Workshop, Kingdom Death, Corvus Belli, Privateer Press, etc.)
2. WATERMARKS: Any photographer/company watermarks
3. COPYRIGHTED CHARACTERS: Is this clearly a specific copyrighted character?
   (superhero, anime character, video game character, film character)
4. PACKAGING: Is branded packaging visible?
5. COPYRIGHT TEXT: Any visible copyright notices (c), TM, (R)

Respond in JSON format ONLY:
{
  "risk_level": "safe" | "warning" | "block",
  "issues": ["list of specific issues found"],
  "description": "brief description of what the image shows",
  "recommendation": "what action to take"
}

If the image shows a generic fantasy/historical/sci-fi figure with no visible
branding, respond with risk_level "safe".
If there are minor issues (small watermark, ambiguous character), use "warning".
If the image clearly shows a major brand's copyrighted character or prominent
branding, use "block"."""


def _load_image_cache():
    if IMAGE_CACHE_FILE.exists():
        return json.loads(IMAGE_CACHE_FILE.read_text())
    return {}


def _save_image_cache(cache):
    IMAGE_CACHE_FILE.write_text(json.dumps(cache, indent=2))


def scan_image(image_url, api_key=None):
    """
    Scan a product image using Claude Vision API.
    Returns (risk_level, issues, description, recommendation).
    """
    api_key = api_key or config.ANTHROPIC_API_KEY
    if not api_key or api_key == "sk-ant-xxx":
        return "skip", ["No Anthropic API key configured"], "", "Skipped — set ANTHROPIC_API_KEY"

    # Check cache
    cache = _load_image_cache()
    if image_url in cache:
        c = cache[image_url]
        return c["risk_level"], c["issues"], c["description"], c["recommendation"]

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 500,
                "system": VISION_SYSTEM_PROMPT,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {"type": "url", "url": image_url},
                            },
                            {
                                "type": "text",
                                "text": "Scan this product image for compliance issues.",
                            },
                        ],
                    }
                ],
            },
            timeout=30,
        )

        if resp.status_code != 200:
            return "warning", [f"API error: {resp.status_code}"], "", "Manual review needed"

        data = resp.json()
        text = data["content"][0]["text"]

        # Parse JSON from response (handle markdown code blocks)
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        result = json.loads(text)
        risk = result.get("risk_level", "warning")
        issues = result.get("issues", [])
        desc = result.get("description", "")
        rec = result.get("recommendation", "")

        # Cache result
        cache[image_url] = {"risk_level": risk, "issues": issues, "description": desc, "recommendation": rec}
        _save_image_cache(cache)

        return risk, issues, desc, rec

    except Exception as e:
        return "warning", [f"Scan error: {str(e)}"], "", "Manual review needed"


def scan_images_batch(image_urls, api_key=None):
    """Scan a batch of images with rate limiting."""
    results = {}
    total = len(image_urls)
    scanned = 0

    for i in range(0, total, config.IMAGE_SCAN_BATCH_SIZE):
        batch = image_urls[i : i + config.IMAGE_SCAN_BATCH_SIZE]
        for url in batch:
            if scanned >= config.MAX_IMAGE_SCANS_PER_RUN:
                results[url] = ("skip", ["Rate limit reached"], "", "Try again next run")
                continue
            results[url] = scan_image(url, api_key)
            scanned += 1
        if i + config.IMAGE_SCAN_BATCH_SIZE < total:
            time.sleep(config.IMAGE_SCAN_DELAY)
        print(f"  Scanned {min(scanned, total)}/{total} images...", end="\r")

    print()
    return results


# ═══════════════════════════════════════════════════════════════
# COMPLIANCE REPORT
# ═══════════════════════════════════════════════════════════════

def compliance_report(products, image_results=None):
    """
    Run compliance on a list of products and generate reports.
    Each product is a dict with at least 'title' and optionally 'image_url'.
    Returns (blocked, warnings, clean, changed) lists.
    """
    blocked = []
    warnings = []
    clean = []
    changed = []

    for product in products:
        original_title = product.get("title", "")
        new_title, issues, action = scan_title(original_title)

        if action == "block":
            blocked.append({**product, "original_title": original_title, "issues": issues})
            continue

        # Image scan results
        img_risk = "safe"
        img_issues = []
        if image_results and product.get("image_url"):
            img_url = product["image_url"]
            if img_url in image_results:
                img_risk, img_issues, _, _ = image_results[img_url]

        if img_risk == "block":
            blocked.append({
                **product,
                "original_title": original_title,
                "issues": issues + [f"IMAGE: {i}" for i in img_issues],
            })
            continue

        # Apply strict mode
        if config.COMPLIANCE_MODE == "strict" and img_risk == "warning":
            warnings.append({
                **product,
                "original_title": original_title,
                "new_title": new_title,
                "issues": issues + [f"IMAGE: {i}" for i in img_issues],
            })
        elif img_risk == "warning":
            warnings.append({
                **product,
                "original_title": original_title,
                "new_title": new_title,
                "issues": [f"IMAGE: {i}" for i in img_issues],
            })
        elif action == "clean":
            changed.append({
                **product,
                "original_title": original_title,
                "new_title": new_title,
                "issues": issues,
            })
        else:
            clean.append({**product, "title": new_title})

        # Update title in product
        product["title"] = new_title

    return blocked, warnings, clean, changed


def write_report(blocked, warnings, clean, changed, output_dir="."):
    """Write compliance report and CSV files."""
    output_dir = Path(output_dir)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(blocked) + len(warnings) + len(clean) + len(changed)

    # ── Text report ──
    lines = [
        "CASTFORGE COMPLIANCE REPORT",
        f"Generated: {now}",
        f"Total products scanned: {total}",
        "",
        f"BLOCKED (DO NOT LIST): {len(blocked)}",
    ]
    for p in blocked:
        reasons = "; ".join(p["issues"])
        lines.append(f"  - {p['original_title']}")
        lines.append(f"    Reason: {reasons}")
    lines.append("")

    lines.append(f"TITLE CHANGES: {len(changed)}")
    for p in changed:
        lines.append(f"  - BEFORE: {p['original_title']}")
        lines.append(f"    AFTER:  {p['new_title']}")
        lines.append(f"    REASON: {'; '.join(p['issues'])}")
    lines.append("")

    lines.append(f"IMAGE WARNINGS (manual review needed): {len(warnings)}")
    for p in warnings:
        img_issues = [i for i in p["issues"] if i.startswith("IMAGE:")]
        lines.append(f"  - {p.get('new_title', p.get('original_title', ''))}")
        lines.append(f"    Issues: {'; '.join(img_issues) if img_issues else '; '.join(p['issues'])}")
    lines.append("")

    lines.append(f"CLEAN (no changes needed): {len(clean)}")
    lines.append("")

    report_path = output_dir / "castforge_compliance_report.txt"
    report_path.write_text("\n".join(lines))
    print(f"  Saved {report_path}")

    # ── CSV files ──
    _write_csv(output_dir / "blocked_products.csv", blocked, ["title", "original_title", "issues"])
    _write_csv(output_dir / "warnings_products.csv", warnings, ["title", "new_title", "original_title", "issues"])
    _write_csv(output_dir / "clean_products.csv", clean + changed, ["title"])

    return report_path


def _write_csv(path, items, fields):
    """Write a list of dicts to CSV."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for item in items:
            row = {}
            for field in fields:
                val = item.get(field, "")
                if isinstance(val, list):
                    val = "; ".join(str(v) for v in val)
                row[field] = val
            writer.writerow(row)
    print(f"  Saved {path} ({len(items)} rows)")
