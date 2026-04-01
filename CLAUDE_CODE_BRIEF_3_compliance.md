# CLAUDE CODE BRIEF: CastForge Compliance System
# =================================================
#
# INSTRUCTIONS FOR LOUIS:
# 1. Open Claude Code
# 2. Paste this entire brief
# 3. Tell Claude Code: "Build the CastForge compliance system using this brief"
# 4. This integrates into the product pipeline from Brief #2
#
# WHAT THIS DOES:
# - Scans every product title for trademarked brands, copyrighted IP, real people
# - Strips or rewrites dangerous terms while keeping the product descriptive
# - Scans product images using Claude Vision API for brand logos/watermarks
# - Blocks products that are too risky to list (direct counterfeits)
# - Generates a compliance report showing what was changed and why
# - Runs BEFORE upload — nothing goes to Shopify without passing compliance
#
# ═══════════════════════════════════════════════════

"""
BUILD A PYTHON MODULE: compliance.py

This module has three main functions:
  1. scan_title(title) → returns cleaned title + list of issues found
  2. scan_image(image_url) → returns risk_level + list of issues found
  3. compliance_report(products) → returns summary of all issues

═══════════════════════════════════════
SECTION 1: TITLE COMPLIANCE
═══════════════════════════════════════

The title scanner must:
1. Check against all blocklists below
2. Strip blocked terms
3. Rewrite the title to be descriptive but legally safe
4. Remove manufacturer catalog/SKU numbers
5. Remove real people's names (living or recently deceased)
6. Remove copyrighted character names
7. Remove brand names and game system names

After stripping, the title should still make sense as a product listing.
If stripping would leave an empty or nonsensical title, flag for MANUAL REVIEW.

REWRITING RULES:
- "Avatars of War 28306 Wizard Mage" → "Fantasy Wizard Mage Miniature"
- "Kingdom Death Monster Twilight Knight" → "Dark Fantasy Twilight Knight Figure"
- "Brad Pitt The Film Fury (5 People)" → "WWII Tank Crew Set (5 Figures)"
- "Skarre, Queen of the Broken Coast" → "Pirate Queen Fantasy Bust"
- "GK Resin Dragon Figure" → "Resin Dragon Figure"
- "28279 Kingdom Death KD Fighter" → "Fantasy Female Fighter Miniature"
- "Wargame 28519 JSA Army Pack" → "Sci-Fi Infantry Army Pack"
- "X-103 Skarre Queen of the Broken Coast" → "Pirate Queen Miniature Bust"

The pattern is: strip the brand/IP, keep the descriptive words, and if needed
add generic category words to replace what was removed.

═══════════════════════════════════════
SECTION 2: COMPREHENSIVE BLOCKLISTS
═══════════════════════════════════════

### TIER 1 — HARD BLOCK (remove product entirely, do NOT list)
These are products that cannot be safely relisted even with title changes,
because the sculpt itself is a direct copy of copyrighted IP:

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
    "transformers", "gundam" (only if Bandai branded),
    "warhammer" (if it IS a GW sculpt, not just compatible),
]

### TIER 2 — STRIP BRAND, KEEP PRODUCT (remove brand name from title)
These are brands/companies whose NAME must be removed, but the generic
product can still be listed if the title is rewritten:

MINIATURE_BRANDS_STRIP = [
    # The GK trademark Louis specifically mentioned
    "gk", "gk miniatures", "gk model",
    
    # Major miniatures companies (very litigious)
    "games workshop", "gw", "citadel miniatures", "forge world",
    "warhammer", "warhammer 40k", "warhammer 40,000", "age of sigmar",
    "kill team", "necromunda", "blood bowl", "underworlds",
    
    # Kingdom Death (extremely litigious)
    "kingdom death", "kingdom death monster", "kdm", "kd monster",
    "dead kingdom",  # common AliExpress misspelling
    
    # Corvus Belli / Infinity
    "corvus belli", "infinity the game", "infinity n4",
    "ariadna", "panoceania", "haqqislam", "yu jing",
    "nomads", "combined army", "tohaa", "aleph",
    "shasvastii", "jsa",  # faction names are trademarked
    
    # Privateer Press
    "privateer press", "warmachine", "hordes",
    "khador", "cygnar", "menoth", "cryx",
    "skorne", "trollbloods", "circle orboros",
    
    # Para Bellum
    "para bellum", "conquest", "the last argument of kings",
    
    # Other miniature brands
    "avatars of war", "avatar of war",
    "dark sword miniatures", "dark sword",
    "reaper miniatures", "reaper minis",
    "wizkids", "nolzur",
    "moonstone", "moonstone the game",
    "gamezone", "gamezone miniatures",
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
    "tank", (only when it's a brand name, not the vehicle)
    "mantic", "mantic games",
    "frostgrave",
    "northstar", "north star military figures",
    "perry miniatures", "perry twins",
    "warlord games", "bolt action",
    "battlefront", "flames of war",
    "wyrd", "malifaux",
    "atomic mass games", "star wars legion",
    "fantasy flight", "ffg",
    "paizo", "pathfinder" (as brand, not generic),
    "wizards of the coast", "wotc",
    "hasbro",
    "cmon", "cool mini or not",
    "zombicide",
    "steamforged", "guild ball",
    "catalyst game labs", "battletech",
]

SCULPTOR_NAMES_STRIP = [
    # Individual sculptors whose names indicate the original brand
    "michael kontraros", "raul garcia latorre", "jason wiebe",
    "jacques alexandre gillois", "pedro fernandez ramos",
    "jose david cabrera", "juan jose baena", "kirill kanaev",
    "romain van den bogaert", "luca coltelli",
    "sergio calvo", "alfonso giraldes", "banshee",
    "heriberto martinez valle", "yeong jin jeon",
    "jin young song", "mj kim",
]

### TIER 3 — STRIP REFERENCE NUMBERS
These are manufacturer catalog/SKU numbers that trace back to the original brand:

CATALOG_NUMBER_PATTERNS = [
    r"^[A-Z]-?\d{3}",          # X-103, X-124, X-090 etc (bust catalog numbers)
    r"^\d{5}\b",                # 28220, 28306, 35607 etc (brand catalog numbers)
    r"^Ref\.\s*[A-Z]\d+",      # Ref. R55 etc
    r"\b\d{4,5}[A-Z]?\b",      # 5-digit catalog numbers mid-title
    r"^[A-Z]{2,3}-\d{3,4}",    # GK-1234, MK-567 style codes
]
# After stripping, also remove orphaned numbers at the start of titles
# like "28220 " or "35607 " that are clearly catalog references.
# BUT preserve scale numbers like "1/35", "28mm", "54mm", "75mm", "90mm"

### TIER 4 — REAL PEOPLE (strip name, keep description)
REAL_PEOPLE_STRIP = [
    # Living celebrities
    "brad pitt", "sean connery", "arnold schwarzenegger",
    "keanu reeves", "johnny depp",
    # Recently deceased
    "queen elizabeth",
    # Political figures (living)
    "putin", "trump", "biden", "xi jinping",
    # Historical figures are GENERALLY FINE to keep:
    # Napoleon, Caesar, Alexander the Great, Leonidas, etc.
    # But strip if paired with a copyrighted depiction
    # (e.g. "Sean Connery" Crusaders = the film "Kingdom of Heaven")
]

COPYRIGHTED_FILMS_STRIP = [
    # Film names that indicate the sculpt copies a copyrighted character
    "fury", (when paired with "brad pitt" or "film")
    "kingdom of heaven",
    "300", (when it's clearly the film, e.g. "Leonidas 300")
    "gladiator", (when it's clearly the film)
    "saving private ryan",
    "band of brothers",
    "black hawk down",
    "braveheart",
    "the pacific",
    "dunkirk",
    "1917",
    "hacksaw ridge",
    "schindler",
]

### TIER 5 — GAME-SPECIFIC TERMS (strip faction/unit names)
GAME_SPECIFIC_TERMS = [
    # Warhammer 40K specific
    "space marine", "primaris", "intercessor", "hellblaster",
    "ork", "tyranid", "necron", "tau", "eldar", "craftworld",
    "aeldari", "drukhari", "genestealer", "chaos space marine",
    "death guard", "thousand sons", "world eater", "emperor's children",
    "imperial guard", "astra militarum", "adeptus mechanicus",
    "sisters of battle", "adepta sororitas", "custodes", "grey knight",
    "blood angel", "dark angel", "space wolf", "ultramarine",
    "imperial fist", "iron hand", "raven guard", "salamander",
    "deathwatch", "black templar",
    
    # Age of Sigmar specific
    "stormcast", "nighthaunt", "ossiarch", "lumineth",
    "seraphon", "sylvaneth", "fyreslayer", "kharadron",
    "idoneth", "daughters of khaine", "hedonite",
    "slaanesh", "nurgle", "tzeentch", "khorne",
    "skaven", "gloomspite", "ogor", "sons of behemat",
    "flesh-eater", "soulblight",
    
    # Infinity specific
    "tag", (when clearly referring to Infinity TAGs)
    "hackable", "fireteam", "haris",
    
    # Kingdom Death specific
    "lantern year", "showdown", "hunt phase",
    "twilight knight", (when paired with KD references)
    "flower knight", "lion knight", "dragon king",
    "watcher", "gold smoke knight",
    "pinup" (when paired with KD — "Pinup" alone is fine),
    
    # Privateer Press specific
    "warcaster", "warjack", "warbeast",
    "focus", "fury" (game mechanic context),
]

═══════════════════════════════════════
SECTION 3: TITLE REWRITING ENGINE
═══════════════════════════════════════

After stripping blocked terms, the rewriter must:

1. If the remaining title is still descriptive (>3 meaningful words), clean it up
2. If the remaining title is too short/vague, enrich it using the CATEGORY
   detected by the categorizer:
   - Wargaming products → add "Miniature", "Tabletop", scale
   - Scale models → add "Resin Model Kit", scale
   - Fantasy/anime figures → add "Resin Figure", "Display Figure"
   - Terrain → add "Tabletop Terrain", "Scenery"
   - Busts → add "Resin Bust", "Display Bust"

3. Always ensure the final title includes:
   - What the product IS (figure, miniature, bust, terrain, vehicle)
   - The scale if known (28mm, 1/35, 54mm etc.)
   - "Resin" or "Resin Kit" somewhere
   - A descriptive element (medieval knight, WWII soldier, fantasy dragon, etc.)

4. NEVER include:
   - Brand names
   - Sculptor names  
   - Catalog numbers
   - Real people's names
   - Film/show names
   - Game-specific faction names
   - "AliExpress", "dropship", "wholesale", "free shipping"
   - "GK", "GW", "KD", "KDM" or any brand abbreviation

5. Title should feel like a PREMIUM hobby store, not an AliExpress listing.
   Good: "Medieval Knight Templar 54mm Resin Figure — Unpainted Assembly Kit"
   Bad: "Resin kit 28306 Avatars of War Wizard Mage"

EXAMPLES:

INPUT: "Model kit Resin kit Avatars of War 28306 Wizard Mage"
OUTPUT: "Fantasy Wizard Mage 28mm Resin Miniature — Unpainted Kit"
REASON: Stripped "Avatars of War" (brand) and "28306" (catalog number)

INPUT: "Resin kit 28279 Kingdom Death KD Fighter"
OUTPUT: "Dark Fantasy Female Fighter Resin Miniature — Unpainted Kit"
REASON: Stripped "Kingdom Death", "KD" (brand), "28279" (catalog)

INPUT: "1/35 Model kit Resin kit Brad Pitt The Film Fury (5 People)"
OUTPUT: "WWII Tank Crew Set (5 Figures) 1/35 Scale Resin Kit — Unpainted"
REASON: Stripped "Brad Pitt" (real person) and "The Film Fury" (copyrighted film)

INPUT: "Wargame Resin kit 28424 Shasvastii Action Pack"
OUTPUT: "Sci-Fi Alien Infantry Action Pack Resin Miniatures — Unpainted"
REASON: Stripped "Shasvastii" (Corvus Belli trademark), "28424" (catalog)

INPUT: "X-103 Skarre, Queen of the Broken Coast"
OUTPUT: "Pirate Queen Fantasy Bust — Resin Display Figure"
REASON: Stripped "X-103" (catalog), "Skarre" (Privateer Press character name)

INPUT: "GK Dragon Knight 1/10"
OUTPUT: "Dragon Knight 1/10 Scale Resin Bust — Collector Display"
REASON: Stripped "GK" (trademark)

INPUT: "54mm Resin kit Resin kit Sun King - Louis XIV"
OUTPUT: "Sun King Louis XIV 54mm Resin Figure — Historical Collectible"
REASON: Historical figure = SAFE. Just cleaned up duplicate "Resin kit"

INPUT: "1 35 Resin kit Panzer Tank 2"
OUTPUT: "WWII German Panzer Tank 1/35 Scale Resin Model Kit — Unpainted"
REASON: "Panzer" is a generic German word, not trademarked. Safe.

═══════════════════════════════════════
SECTION 4: IMAGE COMPLIANCE SCANNER
═══════════════════════════════════════

Use the Anthropic Claude API (claude-sonnet-4-20250514) with vision to scan each
product image. This is the AI image scanning Louis asked for.

For each image, send this prompt to Claude:

---
SYSTEM: You are a copyright compliance scanner for an e-commerce store.
Analyze this product image and report ANY of the following issues:

1. BRAND LOGOS: Any visible brand logos, trademarks, or company names
   (Games Workshop, Kingdom Death, Corvus Belli, Privateer Press, etc.)
2. WATERMARKS: Any photographer/company watermarks
3. COPYRIGHTED CHARACTERS: Is this clearly a specific copyrighted character?
   (superhero, anime character, video game character, film character)
4. PACKAGING: Is branded packaging visible?
5. COPYRIGHT TEXT: Any visible copyright notices (©, ™, ®)

Respond in JSON format:
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
branding, use "block".
---

Processing rules:
- "safe" → proceed with upload
- "warning" → flag for manual review, upload as draft (unpublished)
- "block" → do NOT upload, add to blocked_products.csv for review

Rate limit: Process images in batches of 10 with 1-second delay between calls.
Cache results so re-running doesn't re-scan already-processed images.

═══════════════════════════════════════
SECTION 5: COMPLIANCE REPORT
═══════════════════════════════════════

After processing all products, generate a compliance report:

castforge_compliance_report.txt:

CASTFORGE COMPLIANCE REPORT
Generated: {date}
Total products scanned: {N}

BLOCKED (DO NOT LIST): {count}
  - {title} → Reason: {reason}
  - ...

TITLE CHANGES: {count}
  - BEFORE: {original_title}
    AFTER:  {new_title}
    REASON: {what was stripped and why}
  - ...

IMAGE WARNINGS (manual review needed): {count}
  - {title} → {image_issue}
  - ...

CLEAN (no changes needed): {count}

Also output:
- blocked_products.csv (products that should NOT be listed)
- warnings_products.csv (products needing manual image review)
- clean_products.csv (ready to upload)

═══════════════════════════════════════
SECTION 6: INTEGRATION WITH PIPELINE
═══════════════════════════════════════

This compliance module must run BEFORE upload. The pipeline order is:

1. Read AliExpress CSV
2. Run COMPLIANCE SCAN on every title
3. Run COMPLIANCE SCAN on every image (optional — can be slow for 5000+ products)
4. Categorize clean products
5. Process images (background removal + branding)
6. Upload to Shopify

In main.py, add:
  python main.py comply <input.csv>     — Run compliance scan only (no upload)
  python main.py comply-images <input.csv> — Scan images via Claude Vision
  python main.py upload <input.csv>     — Full pipeline WITH compliance

The "upload" command should ALWAYS run compliance first and refuse to upload
any product that fails.

═══════════════════════════════════════
SECTION 7: ONGOING COMPLIANCE
═══════════════════════════════════════

Also build a small utility:
  python main.py audit — Scans ALL existing Shopify products for compliance issues

This fetches all products from the Shopify API, runs the title scanner on each,
and outputs a report of any products that should be reviewed or delisted.

This is important because new trademarks get registered, and brands that
weren't previously enforcing may start sending takedown notices.

═══════════════════════════════════════
CONFIGURATION
═══════════════════════════════════════

In config.py add:
  ANTHROPIC_API_KEY = "sk-ant-..."  # For image scanning via Claude Vision
  COMPLIANCE_MODE = "strict"  # "strict" blocks anything uncertain, "moderate" allows warnings through
  SCAN_IMAGES = True  # Set False to skip image scanning (faster but less safe)
  MAX_IMAGE_SCANS_PER_RUN = 500  # Rate limit for Claude API
  
Ask Louis for his Anthropic API key if he wants image scanning enabled.
"""
