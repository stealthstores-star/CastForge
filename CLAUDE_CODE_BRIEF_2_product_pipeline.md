# CLAUDE CODE BRIEF: CastForge Product Pipeline
# ================================================
#
# INSTRUCTIONS FOR LOUIS:
# 1. Open Claude Code in terminal
# 2. Paste this entire file as context
# 3. Tell Claude Code: "Build the CastForge product pipeline using this brief"
# 4. Point it at your AliExpress scraper CSV files
#
# WHAT THIS DOES:
# - Reads AliExpress scraper CSVs (auto-detects column names)
# - Categorizes every product into the correct CastForge collection using keyword scoring
# - Cleans titles (removes AliExpress spam)
# - Calculates markup pricing ($, with compare-at for sale badges)
# - Removes image backgrounds and composites onto branded dark studio shots
# - Generates SEO-optimized descriptions
# - Uploads to Shopify via Admin API with correct collection assignments
# - Tags products for smart collections (new, bestseller, bundle)
#
# PRE-REQUISITES:
# - Python 3.10+
# - pip install requests Pillow rembg onnxruntime
# - collection_map.json from Brief #1 (store setup)
# - Shopify API credentials
# - AliExpress scraper CSV files
#
# ═══════════════════════════════════════════════════

"""
BUILD A COMPLETE PYTHON PROJECT with these files:

PROJECT STRUCTURE:
  castforge-pipeline/
  ├── config.py          — credentials, pricing, settings
  ├── categorizer.py     — keyword-based product categorization
  ├── image_processor.py — background removal + branded compositing
  ├── uploader.py        — Shopify Admin API bulk upload
  ├── main.py            — CLI orchestrator
  └── requirements.txt

═══════════════════════════════════════
config.py — SETTINGS
═══════════════════════════════════════

Ask me for:
- SHOPIFY_STORE (myshopify.com subdomain)
- SHOPIFY_ACCESS_TOKEN (shpat_ token)

Settings:
- MARKUP_MULTIPLIER = 2.8  (AliExpress cost × 2.8 = sell price)
- COMPARE_AT_MULTIPLIER = 3.8  (creates "was" price for sale badges)
- MIN_PRICE_USD = 9.99
- ROUND_TO_99 = True  (e.g. $24.99 not $24.37)
- IMAGE_OUTPUT_SIZE = (1200, 1200)
- IMAGE_BG_COLOR = (13, 13, 13)  — matches CastForge dark theme #0D0D0D
- IMAGE_ACCENT_COLOR = (245, 158, 11)  — amber #F59E0B
- BATCH_SIZE = 50
- RATE_LIMIT_DELAY = 0.5

═══════════════════════════════════════
categorizer.py — PRODUCT CATEGORIZATION
═══════════════════════════════════════

Build a keyword scoring engine. For each product title + description, score
against every category's keyword list. Highest score wins.

CATEGORY TAXONOMY (category_handle → keywords):

WARGAMING:
  wargaming-infantry: infantry, troops, soldiers, squad, regiment, platoon,
    guardsmen, warriors, militia, marines, space marine, battle sisters,
    skeletons, zombies, undead, orc boyz, goblins, elves, dwarf warriors,
    sci-fi troops, clone, stormtroopers
  wargaming-vehicles-mechs: mech, walker, titan, dreadnought, warjack,
    battle suit, robot, war machine, tank miniature, hover tank, grav tank,
    sentinel, knight, stompa, gorkanaut, battletech
  wargaming-monsters-creatures: monster, creature, beast, demon, daemon,
    dragon miniature, hydra, wyrm, wyvern, giant, troll, ogre, minotaur,
    spider, brood, swarm, cthulhu, eldritch, tyranid, xenomorph
  wargaming-heroes-characters: hero, commander, captain, general, warlord,
    champion, leader, character, wizard, sorcerer, mage, psyker, warlock,
    paladin, lord, king, queen, assassin, rogue, ranger, commissar, inquisitor,
    chaplain, necromancer
  wargaming-army-bundles: army, bundle, starter, lot, set of, warband,
    regiment set, army box, kill team, patrol, 10pc, 20pc, 5pc, mega bundle

SCALE MODELS:
  scale-military-vehicles: 1/72, 1/35, 1/48, 1/76, 1/144, tank, panzer,
    tiger, sherman, t-34, leopard, abrams, halftrack, armored car, artillery,
    howitzer, ww2 vehicle, wwii, military model, afv
  scale-aircraft: aircraft, airplane, plane, fighter, bomber, spitfire,
    mustang, p-51, messerschmitt, zero, corsair, hurricane, lancaster,
    jet fighter, f-16, helicopter, apache, aviation
  scale-ships-naval: ship, battleship, destroyer, cruiser, carrier, submarine,
    u-boat, frigate, naval, warship, bismarck, yamato, boat model
  scale-cars-motorcycles: car model, race car, rally, f1, formula, motorcycle,
    motorbike, truck, muscle car, classic car, sports car, 1/24, 1/18

ANIME & FANTASY FIGURES:
  anime-characters: anime, manga, waifu, bishoujo, naruto, one piece,
    dragon ball, demon slayer, jujutsu, my hero academia, evangelion,
    sailor moon, fate, kawaii, otaku
  fantasy-warriors: fantasy figure, barbarian, viking, gladiator, samurai,
    knight figure, crusader, elven warrior, dark elf, female warrior,
    amazon, valkyrie, berserker, conan
  scifi-figures: sci-fi figure, cyberpunk, robot figure, android, cyborg,
    space, mecha pilot, power armor, alien figure, post-apocalyptic
  busts-portraits: bust, portrait, head, torso, 1/10 bust, 1/12 bust,
    display bust, pedestal, museum piece

DIORAMA & TERRAIN:
  terrain-bases-plinths: base, plinth, display base, scenic base, round base,
    movement tray, magnetic base
  terrain-scenery: scenery, scatter terrain, barricade, wall, fence, crate,
    barrel, objective marker, campfire, bridge
  terrain-buildings-ruins: building, ruin, ruins, tower, castle, church,
    temple, house, fortress, bunker, watchtower, gothic, medieval
  terrain-natural: tree, forest, rock, boulder, cliff, hill, river,
    mushroom, crystal, cave, swamp, bush
  terrain-props: prop, accessory, diorama, weapon rack, treasure chest,
    throne, altar, portal, tombstone, grave, cart

SCORING RULES:
- Each keyword match in title = +3 points
- Each keyword match in description = +1 point
- Each NEGATIVE keyword match = -5 points
  (e.g. "vehicle" is negative for infantry, "bust" is negative for monsters)
- Products scoring < 2 go to "uncategorized" for manual review
- Products get tagged with parent category name for smart collections

TITLE CLEANING:
Remove these from AliExpress titles (case-insensitive):
  free shipping, hot sale, new arrival, best quality, wholesale, dropship,
  aliexpress, cheap, high quality, top quality, brand new, factory direct,
  %% off, limited time, flash sale, big sale, in stock, fast delivery,
  us warehouse
Then title-case the result (preserving scale notations like 1/72).

DESCRIPTION GENERATION:
For each product, generate a clean HTML description:
  <h3>{Product Type} — {Category Name}</h3>
  <p>{Cleaned title}. Premium resin model requiring assembly and painting.
  Perfect for hobbyists and collectors.</p>
  <h4>Details</h4>
  <ul>
    <li>Material: High-quality resin</li>
    <li>Scale: {detected scale or "Various"}</li>
    <li>Condition: Unassembled, unpainted</li>
    <li>Pieces: Assembly required</li>
  </ul>
  <h4>Shipping</h4>
  <p>Free worldwide shipping. 5-7 day delivery to USA & Europe.</p>

SEO:
  SEO Title: "{Product Title} | CastForge"
  SEO Description: "Shop {title} at CastForge. High-detail resin model kit.
  Free worldwide shipping. 5-7 day delivery."

═══════════════════════════════════════
image_processor.py — IMAGE PIPELINE
═══════════════════════════════════════

For each product image:
1. Download from AliExpress CDN URL (handle redirects, add Referer header)
2. Remove background using rembg (pip install rembg onnxruntime)
3. Create 1200×1200 dark studio canvas (#0D0D0D with subtle radial gradient)
4. Add subtle amber glow behind product (elliptical, blurred, very low opacity)
5. Add drop shadow under product
6. Center product on canvas (scaled to 75% of canvas, slight upward offset)
7. Add dark vignette around edges
8. Add "CASTFORGE" watermark in bottom-right (very subtle, 10% opacity)
9. Add scale badge in bottom-left (e.g. "28mm" or "1/72")
10. Save as JPEG quality 92, 1200×1200

All processing uses Pillow (PIL). The rembg model downloads on first run (~170MB).

For products where rembg fails or image download fails, fall back to:
- Resize original image to 1200×1200 with dark padding
- Add the branding elements anyway

═══════════════════════════════════════
uploader.py — SHOPIFY UPLOAD
═══════════════════════════════════════

Use Shopify Admin REST API to upload products.

For each product:
1. POST /admin/api/2024-10/products.json with:
   - title, body_html, vendor: "CastForge", product_type, tags
   - variants[0]: price, compare_at_price, sku (CF-000001 format),
     inventory_policy: "continue" (always purchasable — dropship),
     requires_shipping: true
   - images[0]: src (either processed local image uploaded to Shopify,
     or the original AliExpress URL as fallback)
   - published: false (review before going live)

2. After product created, assign to collections:
   POST /admin/api/2024-10/collects.json
   - Add to subcategory collection
   - Add to parent category collection

3. Handle rate limiting (429 responses — wait and retry)
4. Log all created product IDs
5. Print summary: X uploaded, Y failed, Z skipped (low confidence)

For images: if processed images exist locally, upload them as files first:
  POST /admin/api/2024-10/products/{id}/images.json
  with base64 encoded image in "attachment" field

═══════════════════════════════════════
main.py — CLI
═══════════════════════════════════════

Commands:
  python main.py process <input.csv>     — Categorize → export Shopify CSV
  python main.py images <input.csv>      — Process all product images
  python main.py upload <input.csv>      — Categorize → images → upload to Shopify
  python main.py stats <input.csv>       — Show category breakdown without uploading

The "upload" command is the main one. Full pipeline:
1. Read CSV (auto-detect columns: title/price/image_url/url/description)
2. Clean titles
3. Categorize all products
4. Print category breakdown and ask for confirmation
5. Process images (with progress bar)
6. Upload to Shopify (with progress)
7. Assign to collections
8. Print final summary

═══════════════════════════════════════
CSV FORMAT (auto-detect these column names):
═══════════════════════════════════════

The AliExpress scraper CSV will have columns like:
  title, price, image_url, url, description
OR:
  product_title, cost, main_image, product_url, details
OR:
  name, ali_price, image, link

Auto-detect by matching against known aliases. Title column is required,
others are optional (will use defaults if missing).

═══════════════════════════════════════
IMPORTANT NOTES:
═══════════════════════════════════════

- NEVER include language like "shipped from overseas", "from China",
  "AliExpress", or "dropship" anywhere in product data
- All prices in USD
- Default weight: 0.5kg per product
- SKU format: CF-XXXXXX (zero-padded 6 digits)
- Tag all products with "new" on first upload (they'll show in New Arrivals)
- Products start as unpublished (draft) so Louis can review before going live
- Rate limit: 0.5s between API calls, handle 429s with exponential backoff
"""
