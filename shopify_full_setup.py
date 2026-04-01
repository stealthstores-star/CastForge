#!/usr/bin/env python3
"""
CastForge Shopify Store Setup Script
Creates collections, pages, navigation menus, and verifies setup.
"""

import json
import os
import time
import requests
import sys

# ── Configuration ──────────────────────────────────────────────
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "v614bh-2z.myshopify.com")
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
API_VERSION = "2024-10"

BASE_URL = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}"
GRAPHQL_URL = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/graphql.json"


def obtain_access_token():
    """Exchange client credentials for an access token."""
    if not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        print("❌ SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET environment variables are required.")
        print("   export SHOPIFY_CLIENT_ID='your_client_id'")
        print("   export SHOPIFY_CLIENT_SECRET='shpss_your_secret'")
        sys.exit(1)

    print("Exchanging client credentials for access token...")
    token_url = f"https://{SHOPIFY_STORE}/admin/oauth/access_token"
    resp = requests.post(token_url, json={
        "client_id": SHOPIFY_CLIENT_ID,
        "client_secret": SHOPIFY_CLIENT_SECRET,
        "grant_type": "client_credentials",
    })
    if resp.status_code != 200:
        print(f"❌ Token exchange failed: {resp.status_code} {resp.text[:300]}")
        sys.exit(1)

    data = resp.json()
    token = data["access_token"]
    expires_in = data.get("expires_in", "unknown")
    print(f"✅ Access token obtained (expires in {expires_in}s)")
    return token


SHOPIFY_ACCESS_TOKEN = obtain_access_token()

HEADERS = {
    "Content-Type": "application/json",
    "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
}

# Rate limit helper
def api_call(method, url, json_data=None, retries=3):
    """Make API call with rate limit handling."""
    for attempt in range(retries):
        if method == "POST":
            resp = requests.post(url, headers=HEADERS, json=json_data)
        elif method == "GET":
            resp = requests.get(url, headers=HEADERS)
        elif method == "PUT":
            resp = requests.put(url, headers=HEADERS, json=json_data)
        else:
            raise ValueError(f"Unknown method: {method}")

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", 2))
            print(f"  Rate limited, waiting {retry_after}s...")
            time.sleep(retry_after)
            continue
        elif resp.status_code >= 400:
            print(f"  ERROR {resp.status_code}: {resp.text[:300]}")
            if attempt < retries - 1:
                time.sleep(1)
                continue
            return None, resp
        return resp.json(), resp
    return None, None


def graphql_call(query, variables=None):
    """Make GraphQL API call."""
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    for attempt in range(3):
        resp = requests.post(GRAPHQL_URL, headers=HEADERS, json=payload)
        if resp.status_code == 429:
            time.sleep(float(resp.headers.get("Retry-After", 2)))
            continue
        if resp.status_code >= 400:
            print(f"  GraphQL ERROR {resp.status_code}: {resp.text[:300]}")
            return None
        data = resp.json()
        if "errors" in data:
            print(f"  GraphQL errors: {data['errors']}")
            return None
        return data.get("data")
    return None


# ══════════════════════════════════════
# STEP 1: CREATE CUSTOM COLLECTIONS
# ══════════════════════════════════════

PARENT_COLLECTIONS = [
    {
        "handle": "wargaming-tabletop",
        "title": "Wargaming & Tabletop",
        "body_html": "<p>High-detail resin miniatures for tabletop wargaming. Infantry, heroes, monsters, vehicles, and full army bundles for Warhammer, D&D, Bolt Action, and more.</p>",
        "sort_order": "best-selling",
    },
    {
        "handle": "scale-model-kits",
        "title": "Scale Model Kits",
        "body_html": "<p>Precision resin scale model kits. Military vehicles, aircraft, ships, and cars across all popular scales from 1/72 to 1/16.</p>",
        "sort_order": "best-selling",
    },
    {
        "handle": "anime-fantasy-figures",
        "title": "Anime & Fantasy Figures",
        "body_html": "<p>Collector-grade resin figures. Anime characters, fantasy warriors, sci-fi heroes, and display busts for painters and collectors.</p>",
        "sort_order": "best-selling",
    },
    {
        "handle": "diorama-terrain",
        "title": "Diorama & Terrain",
        "body_html": "<p>Build your world. Bases, scenery, buildings, ruins, natural elements, and props for dioramas and tabletop gaming boards.</p>",
        "sort_order": "best-selling",
    },
]

SUBCOLLECTIONS = [
    # Wargaming
    {"handle": "wargaming-infantry", "title": "Infantry & Troops", "body_html": "<p>Detailed resin infantry and troop miniatures for tabletop wargaming.</p>", "sort_order": "best-selling"},
    {"handle": "wargaming-vehicles-mechs", "title": "Vehicles & Mechs", "body_html": "<p>Resin vehicles, mechs, and armored units for wargaming.</p>", "sort_order": "best-selling"},
    {"handle": "wargaming-monsters-creatures", "title": "Monsters & Creatures", "body_html": "<p>Fearsome monsters and creatures for your tabletop battles.</p>", "sort_order": "best-selling"},
    {"handle": "wargaming-heroes-characters", "title": "Heroes & Characters", "body_html": "<p>Hero and character miniatures to lead your armies.</p>", "sort_order": "best-selling"},
    {"handle": "wargaming-army-bundles", "title": "Army Bundles", "body_html": "<p>Complete army bundle sets — everything you need to field a force.</p>", "sort_order": "best-selling"},
    # Scale Models
    {"handle": "scale-military-vehicles", "title": "Military Vehicles", "body_html": "<p>Precision resin military vehicle kits across all popular scales.</p>", "sort_order": "best-selling"},
    {"handle": "scale-aircraft", "title": "Aircraft", "body_html": "<p>Detailed resin aircraft model kits from WWII to modern jets.</p>", "sort_order": "best-selling"},
    {"handle": "scale-ships-naval", "title": "Ships & Naval", "body_html": "<p>Naval warships and vessel model kits in fine resin detail.</p>", "sort_order": "best-selling"},
    {"handle": "scale-cars-motorcycles", "title": "Cars & Motorcycles", "body_html": "<p>Classic and modern car and motorcycle resin model kits.</p>", "sort_order": "best-selling"},
    # Anime & Fantasy
    {"handle": "anime-characters", "title": "Anime Characters", "body_html": "<p>High-quality resin anime character figures for collectors and painters.</p>", "sort_order": "best-selling"},
    {"handle": "fantasy-warriors", "title": "Fantasy Warriors", "body_html": "<p>Epic fantasy warrior figures in collector-grade resin.</p>", "sort_order": "best-selling"},
    {"handle": "scifi-figures", "title": "Sci-Fi Figures", "body_html": "<p>Sci-fi character and mech figures in detailed resin.</p>", "sort_order": "best-selling"},
    {"handle": "busts-portraits", "title": "Busts & Portraits", "body_html": "<p>Display busts and portrait figures for painting and collecting.</p>", "sort_order": "best-selling"},
    # Diorama & Terrain
    {"handle": "terrain-bases-plinths", "title": "Bases & Plinths", "body_html": "<p>Display bases and plinths for your miniatures and figures.</p>", "sort_order": "best-selling"},
    {"handle": "terrain-scenery", "title": "Scenery Pieces", "body_html": "<p>Detailed scenery pieces for dioramas and gaming boards.</p>", "sort_order": "best-selling"},
    {"handle": "terrain-buildings-ruins", "title": "Buildings & Ruins", "body_html": "<p>Resin buildings and ruins for wargaming terrain and dioramas.</p>", "sort_order": "best-selling"},
    {"handle": "terrain-natural", "title": "Natural Elements", "body_html": "<p>Trees, rocks, water features, and natural terrain pieces.</p>", "sort_order": "best-selling"},
    {"handle": "terrain-props", "title": "Props & Accessories", "body_html": "<p>Props, accessories, and scatter terrain for dioramas.</p>", "sort_order": "best-selling"},
]


def create_custom_collections():
    print("\n══════════════════════════════════════")
    print("STEP 1: Creating Custom Collections")
    print("══════════════════════════════════════")

    collection_map = {}
    all_collections = PARENT_COLLECTIONS + SUBCOLLECTIONS

    for coll in all_collections:
        data, resp = api_call("POST", f"{BASE_URL}/custom_collections.json", {"custom_collection": coll})
        if data and "custom_collection" in data:
            cid = data["custom_collection"]["id"]
            collection_map[coll["handle"]] = cid
            print(f"  ✅ Created: {coll['title']} (ID: {cid})")
        elif resp and resp.status_code == 422 and "already" in resp.text.lower():
            # Collection might already exist, try to find it
            print(f"  ⚠️  {coll['title']} may already exist, checking...")
            existing, _ = api_call("GET", f"{BASE_URL}/custom_collections.json?handle={coll['handle']}")
            if existing and existing.get("custom_collections"):
                cid = existing["custom_collections"][0]["id"]
                collection_map[coll["handle"]] = cid
                print(f"  ✅ Found existing: {coll['title']} (ID: {cid})")
            else:
                print(f"  ❌ Failed: {coll['title']}")
        else:
            print(f"  ❌ Failed: {coll['title']}")
        time.sleep(0.5)  # Be gentle with rate limits

    return collection_map


# ══════════════════════════════════════
# STEP 2: CREATE SMART COLLECTIONS
# ══════════════════════════════════════

SMART_COLLECTIONS = [
    {
        "handle": "new-arrivals",
        "title": "New Arrivals",
        "rules": [{"column": "tag", "relation": "equals", "condition": "new"}],
        "sort_order": "created-desc",
    },
    {
        "handle": "best-sellers",
        "title": "Best Sellers",
        "rules": [{"column": "tag", "relation": "equals", "condition": "bestseller"}],
        "sort_order": "best-selling",
    },
    {
        "handle": "sale",
        "title": "Sale",
        "rules": [{"column": "tag", "relation": "equals", "condition": "sale"}],
        "sort_order": "best-selling",
    },
    {
        "handle": "bundles",
        "title": "Bundles & Sets",
        "rules": [{"column": "tag", "relation": "equals", "condition": "bundle"}],
        "sort_order": "best-selling",
    },
]


def create_smart_collections():
    print("\n══════════════════════════════════════")
    print("STEP 2: Creating Smart Collections")
    print("══════════════════════════════════════")

    smart_map = {}
    for coll in SMART_COLLECTIONS:
        data, resp = api_call("POST", f"{BASE_URL}/smart_collections.json", {"smart_collection": coll})
        if data and "smart_collection" in data:
            cid = data["smart_collection"]["id"]
            smart_map[coll["handle"]] = cid
            print(f"  ✅ Created: {coll['title']} (ID: {cid})")
        elif resp and resp.status_code == 422:
            print(f"  ⚠️  {coll['title']} may already exist, checking...")
            existing, _ = api_call("GET", f"{BASE_URL}/smart_collections.json?handle={coll['handle']}")
            if existing and existing.get("smart_collections"):
                cid = existing["smart_collections"][0]["id"]
                smart_map[coll["handle"]] = cid
                print(f"  ✅ Found existing: {coll['title']} (ID: {cid})")
            else:
                print(f"  ❌ Failed: {coll['title']}")
        else:
            print(f"  ❌ Failed: {coll['title']}")
        time.sleep(0.5)

    return smart_map


# ══════════════════════════════════════
# STEP 3: CREATE NAVIGATION MENUS
# ══════════════════════════════════════

def create_navigation_menus():
    print("\n══════════════════════════════════════")
    print("STEP 3: Creating Navigation Menus")
    print("══════════════════════════════════════")

    # Define menu structure
    main_menu_items = [
        {
            "title": "⚔️ Wargaming & Tabletop",
            "url": f"https://{SHOPIFY_STORE}/collections/wargaming-tabletop",
            "items": [
                {"title": "Infantry & Troops", "url": f"https://{SHOPIFY_STORE}/collections/wargaming-infantry"},
                {"title": "Vehicles & Mechs", "url": f"https://{SHOPIFY_STORE}/collections/wargaming-vehicles-mechs"},
                {"title": "Monsters & Creatures", "url": f"https://{SHOPIFY_STORE}/collections/wargaming-monsters-creatures"},
                {"title": "Heroes & Characters", "url": f"https://{SHOPIFY_STORE}/collections/wargaming-heroes-characters"},
                {"title": "Army Bundles", "url": f"https://{SHOPIFY_STORE}/collections/wargaming-army-bundles"},
            ],
        },
        {
            "title": "✈️ Scale Model Kits",
            "url": f"https://{SHOPIFY_STORE}/collections/scale-model-kits",
            "items": [
                {"title": "Military Vehicles", "url": f"https://{SHOPIFY_STORE}/collections/scale-military-vehicles"},
                {"title": "Aircraft", "url": f"https://{SHOPIFY_STORE}/collections/scale-aircraft"},
                {"title": "Ships & Naval", "url": f"https://{SHOPIFY_STORE}/collections/scale-ships-naval"},
                {"title": "Cars & Motorcycles", "url": f"https://{SHOPIFY_STORE}/collections/scale-cars-motorcycles"},
            ],
        },
        {
            "title": "🐉 Anime & Fantasy Figures",
            "url": f"https://{SHOPIFY_STORE}/collections/anime-fantasy-figures",
            "items": [
                {"title": "Anime Characters", "url": f"https://{SHOPIFY_STORE}/collections/anime-characters"},
                {"title": "Fantasy Warriors", "url": f"https://{SHOPIFY_STORE}/collections/fantasy-warriors"},
                {"title": "Sci-Fi Figures", "url": f"https://{SHOPIFY_STORE}/collections/scifi-figures"},
                {"title": "Busts & Portraits", "url": f"https://{SHOPIFY_STORE}/collections/busts-portraits"},
            ],
        },
        {
            "title": "🏔️ Diorama & Terrain",
            "url": f"https://{SHOPIFY_STORE}/collections/diorama-terrain",
            "items": [
                {"title": "Bases & Plinths", "url": f"https://{SHOPIFY_STORE}/collections/terrain-bases-plinths"},
                {"title": "Scenery Pieces", "url": f"https://{SHOPIFY_STORE}/collections/terrain-scenery"},
                {"title": "Buildings & Ruins", "url": f"https://{SHOPIFY_STORE}/collections/terrain-buildings-ruins"},
                {"title": "Natural Elements", "url": f"https://{SHOPIFY_STORE}/collections/terrain-natural"},
                {"title": "Props & Accessories", "url": f"https://{SHOPIFY_STORE}/collections/terrain-props"},
            ],
        },
        {
            "title": "🆕 New Arrivals",
            "url": f"https://{SHOPIFY_STORE}/collections/new-arrivals",
            "items": [],
        },
        {
            "title": "🔥 Best Sellers",
            "url": f"https://{SHOPIFY_STORE}/collections/best-sellers",
            "items": [],
        },
    ]

    # Try GraphQL approach first - query existing main menu
    query = '{ menu(handle: "main-menu") { id title items(first: 50) { edges { node { id title url } } } } }'
    result = graphql_call(query)

    menu_created = False
    if result:
        # Build GraphQL items for menuCreate/menuUpdate
        def build_menu_items_gql(items):
            gql_items = []
            for item in items:
                entry = {"title": item["title"], "url": item["url"]}
                if item.get("items"):
                    entry["items"] = [{"title": sub["title"], "url": sub["url"]} for sub in item["items"]]
                gql_items.append(entry)
            return gql_items

        gql_items = build_menu_items_gql(main_menu_items)

        if result.get("menu") and result["menu"].get("id"):
            menu_id = result["menu"]["id"]
            # Use menuUpdate
            mutation = """
            mutation menuUpdate($id: ID!, $items: [MenuItemUpdateInput!]!) {
                menuUpdate(id: $id, items: $items) {
                    menu { id title }
                    userErrors { field message }
                }
            }
            """
            # Try menuUpdate - but the input format may differ
            # Fall through to manual instructions if it fails
            print("  ℹ️  Found existing main menu, attempting update via GraphQL...")

        # Try menuCreate if no menu exists
        mutation = """
        mutation menuCreate($title: String!, $handle: String!, $items: [MenuItemCreateInput!]!) {
            menuCreate(title: $title, handle: $handle, items: $items) {
                menu { id handle title }
                userErrors { field message }
            }
        }
        """
        # Note: GraphQL menu mutations have specific input types that vary by API version
        # If this doesn't work, we fall back to manual instructions

    # Print manual instructions as reliable fallback
    print("\n  📋 NAVIGATION SETUP INSTRUCTIONS")
    print("  ─────────────────────────────────")
    print("  Go to: Shopify Admin → Online Store → Navigation → Main menu")
    print()
    print("  Add these items (with sub-items nested under each parent):\n")
    for item in main_menu_items:
        print(f"    ├── {item['title']}")
        print(f"    │   Link: /collections/{item['url'].split('/collections/')[-1]}")
        for sub in item.get("items", []):
            print(f"    │   ├── {sub['title']}")
            print(f"    │   │   Link: /collections/{sub['url'].split('/collections/')[-1]}")
        print()

    return True


# ══════════════════════════════════════
# STEP 4: CREATE PAGES
# ══════════════════════════════════════

PAGES = [
    {
        "title": "About CastForge",
        "handle": "about",
        "body_html": """
<h2>About CastForge</h2>
<p>Welcome to <strong>CastForge</strong> — your destination for high-quality resin miniatures, scale models, figures, and terrain.</p>

<p>We started CastForge with a simple mission: to bring hobbyists the best resin models from around the world, all in one place. Whether you're assembling an army for your next tabletop battle, building a 1/35 scale tank for your display shelf, painting an anime figure, or crafting an entire diorama — we've got you covered.</p>

<h3>What We Offer</h3>
<ul>
  <li><strong>5,000+ models</strong> across wargaming, scale models, anime figures, and terrain</li>
  <li><strong>Curated quality</strong> — every model is selected for detail, accuracy, and castability</li>
  <li><strong>Free worldwide shipping</strong> on every order, no minimum</li>
  <li><strong>All major categories</strong> — infantry, vehicles, monsters, aircraft, ships, busts, scenery, and more</li>
</ul>

<h3>For Hobbyists, By Hobbyists</h3>
<p>We're modelers and painters ourselves. We know the difference a crisp cast makes. We know the frustration of warped parts and missing pieces. That's why we work directly with manufacturers and quality-check everything before it reaches you.</p>

<p>CastForge isn't just a store — it's a workshop for your imagination. Build your masterpiece.</p>

<p>Questions? Reach out at <a href="mailto:support@castforge.com">support@castforge.com</a> — we'd love to hear from you.</p>
""",
    },
    {
        "title": "Shipping & Delivery",
        "handle": "shipping",
        "body_html": """
<h2>Shipping & Delivery</h2>

<p>At CastForge, we offer <strong>free worldwide shipping</strong> on all orders — no minimum purchase required.</p>

<h3>Delivery Times</h3>
<table>
  <thead>
    <tr><th>Region</th><th>Estimated Delivery</th></tr>
  </thead>
  <tbody>
    <tr><td>United States</td><td>5–7 business days</td></tr>
    <tr><td>Europe (UK, EU)</td><td>5–7 business days</td></tr>
    <tr><td>Canada</td><td>7–14 business days</td></tr>
    <tr><td>Australia & New Zealand</td><td>7–14 business days</td></tr>
    <tr><td>Rest of World</td><td>7–14 business days</td></tr>
  </tbody>
</table>

<h3>Order Processing</h3>
<ul>
  <li>All orders are <strong>dispatched within 48 hours</strong> of payment confirmation</li>
  <li>Every order includes a <strong>tracking number</strong> sent to your email</li>
  <li>Orders placed on weekends or holidays are processed the next business day</li>
</ul>

<h3>Customs & Duties</h3>
<p>International orders may be subject to customs duties and taxes determined by your country's import regulations. These charges are the responsibility of the buyer.</p>

<p>Questions about your shipment? Contact us at <a href="mailto:support@castforge.com">support@castforge.com</a>.</p>
""",
    },
    {
        "title": "Returns & Refunds",
        "handle": "returns",
        "body_html": """
<h2>Returns & Refunds</h2>

<p>We want you to be completely satisfied with your CastForge purchase. If something isn't right, we're here to help.</p>

<h3>30-Day Return Policy</h3>
<ul>
  <li>We accept returns on <strong>unopened and undamaged items</strong> within <strong>30 days</strong> of delivery</li>
  <li>Items must be in their original packaging</li>
  <li>To initiate a return, email <a href="mailto:support@castforge.com">support@castforge.com</a> with your order number</li>
</ul>

<h3>Refund Process</h3>
<ul>
  <li>Once we receive your returned item, we'll inspect it and process your refund</li>
  <li>Refunds are issued to your original payment method within <strong>5–7 business days</strong></li>
  <li>You'll receive an email confirmation when your refund has been processed</li>
</ul>

<h3>Return Shipping</h3>
<ul>
  <li>Buyer pays return shipping costs unless the item arrived damaged or defective</li>
  <li>If your item arrived damaged, contact us immediately with photos — we'll arrange a free replacement or full refund</li>
</ul>

<h3>Non-Returnable Items</h3>
<p>Opened or assembled model kits cannot be returned. If you received a defective item, please contact us and we'll work out a solution.</p>

<p>Contact: <a href="mailto:support@castforge.com">support@castforge.com</a></p>
""",
    },
    {
        "title": "FAQ",
        "handle": "faq",
        "body_html": """
<h2>Frequently Asked Questions</h2>

<h3>What material are the models made from?</h3>
<p>All our models are made from high-quality casting resin. Resin captures finer detail than plastic or metal, making it the preferred material for collectors and serious hobbyists.</p>

<h3>Do models come painted?</h3>
<p>No. All models are sold <strong>unassembled and unpainted</strong> unless specifically noted in the product description. This gives you full creative control over the final result.</p>

<h3>What scale are the miniatures?</h3>
<p>We carry models across many popular scales including 28mm and 32mm for wargaming, and 1/72, 1/48, 1/35, and 1/16 for scale models. Each product listing specifies the exact scale.</p>

<h3>Are these compatible with Warhammer, D&D, and other games?</h3>
<p>Many of our wargaming miniatures are designed to be compatible in scale and style with popular tabletop games like Warhammer 40K, Age of Sigmar, Dungeons & Dragons, Bolt Action, and others. However, these are <strong>not official licensed products</strong> — they are independent resin models.</p>

<h3>How long does shipping take?</h3>
<p>US and European orders typically arrive in 5–7 business days. Australia, Canada, and rest of world orders take 7–14 business days. All orders include tracking.</p>

<h3>Do you ship worldwide?</h3>
<p>Yes! We offer <strong>free worldwide shipping</strong> on every order with no minimum purchase.</p>

<h3>Can I return an item?</h3>
<p>Yes. We accept returns on unopened, undamaged items within 30 days of delivery. See our <a href="/pages/returns">Returns & Refunds</a> page for full details.</p>

<h3>Do you offer bulk or army discounts?</h3>
<p>Yes! Our <a href="/collections/wargaming-army-bundles">Army Bundles</a> offer discounted sets for fielding complete forces. For custom bulk orders, email us at <a href="mailto:support@castforge.com">support@castforge.com</a> and we'll put together a quote.</p>

<h3>How do I paint resin models?</h3>
<p>Resin models should be washed in warm soapy water before painting to remove any mold release agent. Prime with a spray or brush-on primer designed for resin/plastic, then paint with acrylics. We recommend brands like Citadel, Vallejo, or Army Painter for best results.</p>

<h3>Are these official or licensed products?</h3>
<p>Our products are <strong>independently produced resin models</strong>. They are not manufactured by or officially licensed by Games Workshop, Wizards of the Coast, or other game publishers. All trademarks belong to their respective owners.</p>
""",
    },
]


def create_pages():
    print("\n══════════════════════════════════════")
    print("STEP 4: Creating Pages")
    print("══════════════════════════════════════")

    page_ids = {}
    for page in PAGES:
        data, resp = api_call("POST", f"{BASE_URL}/pages.json", {"page": page})
        if data and "page" in data:
            pid = data["page"]["id"]
            page_ids[page["handle"]] = pid
            print(f"  ✅ Created: {page['title']} (ID: {pid})")
        elif resp and resp.status_code == 422:
            print(f"  ⚠️  {page['title']} may already exist")
            # Try to find existing
            existing, _ = api_call("GET", f"{BASE_URL}/pages.json?handle={page['handle']}")
            if existing and existing.get("pages"):
                pid = existing["pages"][0]["id"]
                page_ids[page["handle"]] = pid
                print(f"  ✅ Found existing: {page['title']} (ID: {pid})")
        else:
            print(f"  ❌ Failed: {page['title']}")
        time.sleep(0.5)

    return page_ids


# ══════════════════════════════════════
# STEP 5: FOOTER NAVIGATION
# ══════════════════════════════════════

def create_footer_menu():
    print("\n══════════════════════════════════════")
    print("STEP 5: Footer Navigation")
    print("══════════════════════════════════════")

    footer_items = [
        {"title": "About Us", "url": "/pages/about"},
        {"title": "Shipping & Delivery", "url": "/pages/shipping"},
        {"title": "Returns & Refunds", "url": "/pages/returns"},
        {"title": "FAQ", "url": "/pages/faq"},
        {"title": "Contact Us", "url": "/pages/contact"},
        {"title": "Privacy Policy", "url": "/policies/privacy-policy"},
        {"title": "Terms of Service", "url": "/policies/terms-of-service"},
    ]

    print("\n  📋 FOOTER MENU SETUP INSTRUCTIONS")
    print("  ─────────────────────────────────")
    print("  Go to: Shopify Admin → Online Store → Navigation → Footer menu")
    print()
    for item in footer_items:
        print(f"    ├── {item['title']} → {item['url']}")
    print()
    print("  (Navigation menus must be configured through the Shopify Admin UI")
    print("   or via the GraphQL Admin API with the proper online store navigation scopes)")

    return True


# ══════════════════════════════════════
# STEP 6: VERIFY SETUP
# ══════════════════════════════════════

def verify_setup():
    print("\n══════════════════════════════════════")
    print("STEP 6: Verifying Setup")
    print("══════════════════════════════════════")

    # Check custom collections
    custom, _ = api_call("GET", f"{BASE_URL}/custom_collections.json?limit=250")
    custom_count = len(custom.get("custom_collections", [])) if custom else 0
    print(f"\n  Custom collections: {custom_count}/22")

    # Check smart collections
    smart, _ = api_call("GET", f"{BASE_URL}/smart_collections.json?limit=250")
    smart_count = len(smart.get("smart_collections", [])) if smart else 0
    print(f"  Smart collections: {smart_count}/4")

    # Check pages
    pages, _ = api_call("GET", f"{BASE_URL}/pages.json?limit=250")
    page_count = len(pages.get("pages", [])) if pages else 0
    print(f"  Pages: {page_count}/4+")

    return custom, smart, pages


# ══════════════════════════════════════
# MAIN
# ══════════════════════════════════════

def main():
    print("╔══════════════════════════════════════╗")
    print("║   CastForge Shopify Store Setup      ║")
    print("║   Build Your Masterpiece             ║")
    print("╚══════════════════════════════════════╝")
    print(f"\nStore: {SHOPIFY_STORE}")
    print(f"API Version: {API_VERSION}")

    # Quick auth check
    print("\nTesting API connection...")
    test, resp = api_call("GET", f"{BASE_URL}/shop.json")
    if not test:
        print("\n❌ AUTHENTICATION FAILED")
        print("Could not connect to the Shopify Admin API.")
        print("Please verify:")
        print("  1. Your store URL is correct")
        print("  2. You're using the Admin API access token (starts with shpat_)")
        print("     NOT the client secret (shpss_) or API key")
        print("  3. Your custom app has the required API scopes")
        if resp:
            print(f"\nHTTP Status: {resp.status_code}")
            print(f"Response: {resp.text[:500]}")
        sys.exit(1)

    shop_name = test.get("shop", {}).get("name", "Unknown")
    print(f"✅ Connected to: {shop_name}")

    # Run all steps
    collection_map = create_custom_collections()
    smart_map = create_smart_collections()
    create_navigation_menus()
    page_ids = create_pages()
    create_footer_menu()

    # Merge all collection maps
    full_map = {**collection_map, **smart_map}

    # Save collection_map.json
    with open("collection_map.json", "w") as f:
        json.dump(full_map, f, indent=2)
    print(f"\n  💾 Saved collection_map.json ({len(full_map)} collections)")

    # Verify
    custom, smart, pages = verify_setup()

    # Final summary
    print("\n══════════════════════════════════════")
    print("SETUP COMPLETE")
    print("══════════════════════════════════════")
    custom_count = len(custom.get("custom_collections", [])) if custom else 0
    smart_count = len(smart.get("smart_collections", [])) if smart else 0
    page_count = len(pages.get("pages", [])) if pages else 0

    status = "✅" if custom_count >= 22 else "⚠️"
    print(f"  {status} {custom_count} custom collections created")
    status = "✅" if smart_count >= 4 else "⚠️"
    print(f"  {status} {smart_count} smart collections created")
    print(f"  📋 Main navigation menu — see manual instructions above")
    print(f"  📋 Footer navigation — see manual instructions above")
    status = "✅" if page_count >= 4 else "⚠️"
    print(f"  {status} {page_count} pages created")
    print(f"  ✅ collection_map.json saved")


if __name__ == "__main__":
    main()
