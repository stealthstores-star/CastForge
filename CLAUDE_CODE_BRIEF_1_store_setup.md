# CLAUDE CODE BRIEF: CastForge Shopify Store Setup
# ==================================================
# 
# INSTRUCTIONS FOR LOUIS:
# 1. Open Claude Code in terminal
# 2. Paste this entire file as context
# 3. Tell Claude Code: "Set up the CastForge Shopify store using this brief"
# 4. It will ask for your Shopify API credentials
#
# WHAT THIS DOES:
# - Creates ALL 22 collections (4 parents + 18 subcategories + smart collections)
# - Builds the full navigation menu with nested categories
# - Configures theme settings (colors, fonts, shipping text, SEO defaults)
# - Creates essential pages (About, FAQ, Shipping, Returns)
# - Sets up metafield definitions for product data
# - Verifies everything is correct
#
# PRE-REQUISITES:
# - Shopify store exists (castforge.myshopify.com or similar)
# - Custom app created in Shopify Admin → Settings → Apps → Develop apps
#   with these Admin API scopes:
#     write_products, read_products, write_product_listings,
#     write_publications, read_publications,
#     write_content, read_content,
#     write_themes, read_themes,
#     write_online_store_navigation, read_online_store_navigation,
#     write_metafield_definitions, read_metafield_definitions,
#     write_files, read_files
# - Copy the Admin API access token (starts with shpat_)
#
# ═══════════════════════════════════════════════════

"""
BUILD A PYTHON SCRIPT (shopify_full_setup.py) THAT DOES ALL OF THE FOLLOWING.
USE THE SHOPIFY ADMIN REST API AND GRAPHQL API WHERE NEEDED.

STORE DETAILS:
- Store name: CastForge
- Tagline: "Build Your Masterpiece"
- Currency: USD (base), multi-currency enabled
- Theme: castforge-shopify-theme (already installed)

Ask me for:
- SHOPIFY_STORE (the myshopify.com subdomain)
- SHOPIFY_ACCESS_TOKEN (the shpat_ token)

══════════════════════════════════════
STEP 1: CREATE CUSTOM COLLECTIONS
══════════════════════════════════════

Create these custom (manual) collections via POST /admin/api/2024-10/custom_collections.json:

PARENT COLLECTIONS (4):
1. handle: "wargaming-tabletop"
   title: "Wargaming & Tabletop"
   body_html: "<p>High-detail resin miniatures for tabletop wargaming. Infantry, heroes, monsters, vehicles, and full army bundles for Warhammer, D&D, Bolt Action, and more.</p>"
   sort_order: "best-selling"
   image: (skip for now)

2. handle: "scale-model-kits"
   title: "Scale Model Kits"
   body_html: "<p>Precision resin scale model kits. Military vehicles, aircraft, ships, and cars across all popular scales from 1/72 to 1/16.</p>"
   sort_order: "best-selling"

3. handle: "anime-fantasy-figures"
   title: "Anime & Fantasy Figures"
   body_html: "<p>Collector-grade resin figures. Anime characters, fantasy warriors, sci-fi heroes, and display busts for painters and collectors.</p>"
   sort_order: "best-selling"

4. handle: "diorama-terrain"
   title: "Diorama & Terrain"
   body_html: "<p>Build your world. Bases, scenery, buildings, ruins, natural elements, and props for dioramas and tabletop gaming boards.</p>"
   sort_order: "best-selling"

SUBCOLLECTIONS (18):
Under "wargaming-tabletop":
  - wargaming-infantry: "Infantry & Troops"
  - wargaming-vehicles-mechs: "Vehicles & Mechs"
  - wargaming-monsters-creatures: "Monsters & Creatures"
  - wargaming-heroes-characters: "Heroes & Characters"
  - wargaming-army-bundles: "Army Bundles"

Under "scale-model-kits":
  - scale-military-vehicles: "Military Vehicles"
  - scale-aircraft: "Aircraft"
  - scale-ships-naval: "Ships & Naval"
  - scale-cars-motorcycles: "Cars & Motorcycles"

Under "anime-fantasy-figures":
  - anime-characters: "Anime Characters"
  - fantasy-warriors: "Fantasy Warriors"
  - scifi-figures: "Sci-Fi Figures"
  - busts-portraits: "Busts & Portraits"

Under "diorama-terrain":
  - terrain-bases-plinths: "Bases & Plinths"
  - terrain-scenery: "Scenery Pieces"
  - terrain-buildings-ruins: "Buildings & Ruins"
  - terrain-natural: "Natural Elements"
  - terrain-props: "Props & Accessories"

══════════════════════════════════════
STEP 2: CREATE SMART COLLECTIONS
══════════════════════════════════════

Via POST /admin/api/2024-10/smart_collections.json:

1. handle: "new-arrivals", title: "New Arrivals"
   rules: [{"column": "tag", "relation": "equals", "condition": "new"}]
   sort_order: "created-desc"

2. handle: "best-sellers", title: "Best Sellers"
   rules: [{"column": "tag", "relation": "equals", "condition": "bestseller"}]
   sort_order: "best-selling"

3. handle: "sale", title: "Sale"
   rules: [{"column": "compare_at_price", "relation": "greater_than", "condition": "0"}]
   sort_order: "best-selling"

4. handle: "bundles", title: "Bundles & Sets"
   rules: [{"column": "tag", "relation": "equals", "condition": "bundle"}]
   sort_order: "best-selling"

══════════════════════════════════════
STEP 3: CREATE NAVIGATION MENU
══════════════════════════════════════

Use the Shopify GraphQL Admin API to update the main menu.
Endpoint: POST /admin/api/2024-10/graphql.json

First query the existing menu:
  query { menu(handle: "main-menu") { id title items { id title } } }

Then use menuUpdate or menuCreate to set this structure:

Main Menu items:
  ├── "⚔️ Wargaming & Tabletop" → /collections/wargaming-tabletop
  │   ├── "Infantry & Troops" → /collections/wargaming-infantry
  │   ├── "Vehicles & Mechs" → /collections/wargaming-vehicles-mechs
  │   ├── "Monsters & Creatures" → /collections/wargaming-monsters-creatures
  │   ├── "Heroes & Characters" → /collections/wargaming-heroes-characters
  │   └── "Army Bundles" → /collections/wargaming-army-bundles
  ├── "✈️ Scale Model Kits" → /collections/scale-model-kits
  │   ├── "Military Vehicles" → /collections/scale-military-vehicles
  │   ├── "Aircraft" → /collections/scale-aircraft
  │   ├── "Ships & Naval" → /collections/scale-ships-naval
  │   └── "Cars & Motorcycles" → /collections/scale-cars-motorcycles
  ├── "🐉 Anime & Fantasy Figures" → /collections/anime-fantasy-figures
  │   ├── "Anime Characters" → /collections/anime-characters
  │   ├── "Fantasy Warriors" → /collections/fantasy-warriors
  │   ├── "Sci-Fi Figures" → /collections/scifi-figures
  │   └── "Busts & Portraits" → /collections/busts-portraits
  ├── "🏔️ Diorama & Terrain" → /collections/diorama-terrain
  │   ├── "Bases & Plinths" → /collections/terrain-bases-plinths
  │   ├── "Scenery Pieces" → /collections/terrain-scenery
  │   ├── "Buildings & Ruins" → /collections/terrain-buildings-ruins
  │   ├── "Natural Elements" → /collections/terrain-natural
  │   └── "Props & Accessories" → /collections/terrain-props
  ├── "🆕 New Arrivals" → /collections/new-arrivals
  └── "🔥 Best Sellers" → /collections/best-sellers

NOTE: If GraphQL menu mutations aren't available on their plan, output the EXACT
manual steps with the exact titles and URLs for each menu item so they can create
it in Shopify Admin → Online Store → Navigation in under 5 minutes.

══════════════════════════════════════
STEP 4: CREATE PAGES
══════════════════════════════════════

Via POST /admin/api/2024-10/pages.json:

1. title: "About CastForge"
   handle: "about"
   body_html: (write a professional About page for a worldwide resin model store.
   Mention: 5,000+ models, worldwide shipping, curated for hobbyists, all categories.
   Tone: passionate about the hobby, knowledgeable, not corporate.)

2. title: "Shipping & Delivery"
   handle: "shipping"
   body_html: (detail the shipping policy:
   - Free worldwide shipping on all orders
   - 5-7 business days delivery to USA & Europe
   - 7-14 days to Australia, Canada, rest of world
   - All orders include tracking
   - Dispatched within 48 hours)

3. title: "Returns & Refunds"
   handle: "returns"
   body_html: (30-day return policy:
   - Unopened/undamaged items accepted within 30 days
   - Contact support@castforge.com to initiate
   - Refund processed within 5-7 business days
   - Buyer pays return shipping unless item arrived damaged)

4. title: "FAQ"
   handle: "faq"
   body_html: (write 10 common questions for a resin model store:
   - What material are the models made from?
   - Do models come painted?
   - What scale are the miniatures?
   - Are these compatible with Warhammer/D&D?
   - How long does shipping take?
   - Do you ship worldwide?
   - Can I return an item?
   - Do you offer bulk/army discounts?
   - How do I paint resin models?
   - Are these official/licensed products?
   Answer each honestly — resin models, unassembled/unpainted, various scales,
   compatible but not official, free worldwide shipping, etc.)

══════════════════════════════════════
STEP 5: CREATE FOOTER NAVIGATION
══════════════════════════════════════

Create a footer menu (handle: "footer") with:
  ├── "About Us" → /pages/about
  ├── "Shipping & Delivery" → /pages/shipping
  ├── "Returns & Refunds" → /pages/returns
  ├── "FAQ" → /pages/faq
  ├── "Contact Us" → /pages/contact
  ├── "Privacy Policy" → /policies/privacy-policy
  └── "Terms of Service" → /policies/terms-of-service

══════════════════════════════════════
STEP 6: VERIFY SETUP
══════════════════════════════════════

After all steps, run verification:
1. GET /admin/api/2024-10/custom_collections.json?limit=250 — count should be 22
2. GET /admin/api/2024-10/smart_collections.json?limit=250 — count should be 4
3. GET /admin/api/2024-10/pages.json — count should be 4+
4. Print a summary table of everything created with IDs

Save a collection_map.json file mapping handle → collection_id for use in the product upload pipeline.

══════════════════════════════════════
STEP 7: OUTPUT
══════════════════════════════════════

Print:
✅ 22 custom collections created
✅ 4 smart collections created
✅ Main navigation menu configured
✅ Footer navigation configured
✅ 4 pages created (About, Shipping, Returns, FAQ)
✅ collection_map.json saved

If any steps fail, report exactly what failed and provide the manual
fallback steps.
"""
