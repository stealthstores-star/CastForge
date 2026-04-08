#!/usr/bin/env python3
"""
Generate SEO-rich descriptions for every collection via Claude Haiku,
then push them to Shopify as collection body_html.

Each description is 300-500 words targeting relevant long-tail keywords.
Placed below the product grid, these improve organic search rankings.

Usage: python3 create_collection_seo.py
"""
import json, sys, time
import requests
import config
from uploader import get_shopify_token

# Collection handle → SEO brief
COLLECTIONS = {
    # ── Parent collections ──
    "wargaming-tabletop": {
        "title": "Wargaming & Tabletop Miniatures",
        "keywords": "wargaming miniatures, tabletop miniatures, resin wargaming figures, 28mm miniatures",
        "brief": "Overview of the full wargaming range — infantry, heroes, monsters, vehicles, army bundles. Mention compatibility with popular systems (Warhammer, D&D, Bolt Action, etc). Explain resin quality advantages over plastic."
    },
    "scale-model-kits": {
        "title": "Scale Model Kits",
        "keywords": "scale model kits, resin scale models, 1/35 models, military model kits",
        "brief": "Overview of scale model range — tanks, aircraft, ships, cars. Cover common scales (1/35, 1/48, 1/72). Emphasise resin detail vs injection-moulded plastic. Mention historical accuracy."
    },
    "anime-fantasy-figures": {
        "title": "Anime & Fantasy Figures",
        "keywords": "anime resin figures, fantasy miniatures, resin character figures, collector figures",
        "brief": "Overview of character figure range — anime, fantasy warriors, sci-fi, busts. Highlight display-quality resin detail, painting potential, collector value."
    },
    "diorama-terrain": {
        "title": "Diorama & Terrain",
        "keywords": "wargaming terrain, diorama supplies, tabletop terrain, resin terrain pieces",
        "brief": "Overview of terrain range — buildings, ruins, natural features, bases, props. Cover use in wargaming and diorama building. Mention compatibility with 28mm and various scales."
    },

    # ── Sub-collections ──
    "wargaming-infantry": {
        "title": "Wargaming Infantry",
        "keywords": "wargaming infantry, 28mm soldiers, resin infantry miniatures, WWII miniatures",
        "brief": "Resin infantry for tabletop wargaming and painting. Cover: WWII, modern, historical periods. Mention scale compatibility, painting tips, unit building. Reference Bolt Action, Flames of War."
    },
    "wargaming-heroes-characters": {
        "title": "Heroes & Characters",
        "keywords": "hero miniatures, character miniatures, RPG miniatures, D&D figures resin",
        "brief": "Unique hero and character miniatures for RPGs and wargames. Cover: wizards, commanders, assassins, leaders. Mention D&D, Pathfinder compatibility. Emphasise unique sculpts vs mass-produced plastic."
    },
    "wargaming-monsters-creatures": {
        "title": "Monsters & Creatures",
        "keywords": "monster miniatures, creature miniatures, dragon miniature, demon miniature resin",
        "brief": "Large resin monsters and creatures for tabletop gaming. Cover: dragons, demons, giants, undead. Mention centrepiece models, boss encounters, painting showcase potential."
    },
    "wargaming-vehicles-mechs": {
        "title": "Vehicles & Mechs",
        "keywords": "mech miniatures, walker miniatures, wargaming vehicles, battletech miniatures",
        "brief": "Mechs, walkers, and sci-fi vehicles for wargaming. Cover: dreadnoughts, battle suits, titans. Mention system compatibility, assembly tips for large resin kits."
    },
    "wargaming-army-bundles": {
        "title": "Army Bundles & Starter Sets",
        "keywords": "wargaming army bundle, miniature starter set, kill team alternatives, army box",
        "brief": "Complete army bundles and starter sets. Cover: value vs buying individual, warband building, kill team alternatives. Emphasise savings and ready-to-play collections."
    },
    "scale-military-vehicles": {
        "title": "Scale Military Vehicles",
        "keywords": "1/35 tank model, resin military vehicle, WWII tank model, scale armor model",
        "brief": "Resin military vehicles across scales. Cover: tanks (Tiger, Sherman, T-34), half-tracks, artillery. Mention 1/35 and 1/72 scales, detail comparison with Tamiya/Dragon plastic kits, diorama potential."
    },
    "scale-aircraft": {
        "title": "Scale Aircraft",
        "keywords": "resin aircraft model, 1/48 aircraft, WWII plane model, scale airplane kit",
        "brief": "Resin aircraft models across scales. Cover: WWII fighters, bombers, helicopters, modern jets. Mention 1/48 and 1/72 scales, resin detail advantages for panel lines and cockpits."
    },
    "scale-ships-naval": {
        "title": "Scale Ships & Naval",
        "keywords": "scale ship model, resin warship, 1/700 ship model, naval model kit",
        "brief": "Resin naval models. Cover: battleships, destroyers, submarines, carriers. Mention 1/350 and 1/700 scales, waterline vs full hull, display options."
    },
    "scale-cars-motorcycles": {
        "title": "Scale Cars & Motorcycles",
        "keywords": "resin car model, scale motorcycle, 1/24 car model, classic car miniature",
        "brief": "Resin car and motorcycle models. Cover: classic cars, race cars, motorcycles. Mention 1/24 and 1/12 scales, garage diorama potential, detail quality."
    },
    "fantasy-warriors": {
        "title": "Fantasy Warriors",
        "keywords": "fantasy warrior miniature, knight miniature resin, barbarian figure, medieval miniature",
        "brief": "Fantasy and historical warrior figures. Cover: knights, barbarians, samurai, vikings, gladiators. Mention painting competitions, display quality, RPG use."
    },
    "anime-characters": {
        "title": "Anime Characters",
        "keywords": "anime figure resin, manga miniature, anime garage kit, resin anime statue",
        "brief": "Anime and manga character figures in resin. Cover: garage kit tradition, painting anime figures, scale options, display quality vs PVC figures."
    },
    "scifi-figures": {
        "title": "Sci-Fi Figures",
        "keywords": "sci-fi miniature, cyberpunk miniature, robot miniature resin, space marine alternative",
        "brief": "Sci-fi character figures. Cover: cyberpunk, post-apocalyptic, space marines, robots. Mention wargaming use, painting techniques for metallic/OSL effects."
    },
    "busts-portraits": {
        "title": "Busts & Portraits",
        "keywords": "resin bust miniature, display bust, 1/10 bust, portrait miniature painting",
        "brief": "Display busts and portrait figures. Cover: 1/10, 1/9, 1/8 scales (75mm, 100mm, 200mm), painting showcase potential, competition pieces, display options."
    },
    "terrain-buildings-ruins": {
        "title": "Buildings & Ruins",
        "keywords": "wargaming buildings, ruined building terrain, tabletop ruins, 28mm terrain",
        "brief": "Resin buildings and ruins for wargaming tables. Cover: medieval, WWII, sci-fi ruins. Mention line-of-sight blocking, painting techniques, modular options."
    },
    "terrain-scenery": {
        "title": "Scatter Terrain & Scenery",
        "keywords": "scatter terrain, wargaming scenery, tabletop barricades, terrain pieces",
        "brief": "Scatter terrain and scenery pieces. Cover: barricades, walls, fences, bridges. Mention table coverage, quick painting, game impact."
    },
    "terrain-natural": {
        "title": "Natural Terrain",
        "keywords": "natural terrain miniatures, wargaming trees, rock terrain, forest terrain pieces",
        "brief": "Natural terrain features. Cover: trees, rocks, rivers, caves, crystals. Mention basing, diorama building, versatility across game systems."
    },
    "terrain-bases-plinths": {
        "title": "Bases & Plinths",
        "keywords": "miniature bases, display plinth, scenic base, movement tray",
        "brief": "Display bases, plinths, and movement trays. Cover: scenic bases, round/square options, display plinths for competition pieces, magnetic options."
    },
    "terrain-props": {
        "title": "Props & Accessories Terrain",
        "keywords": "dungeon props miniature, treasure chest miniature, terrain accessories, RPG props",
        "brief": "Terrain props and accessories. Cover: treasure chests, weapon racks, altars, tombstones. Mention RPG encounters, dungeon dressing, objective markers."
    },
    "accessories": {
        "title": "Hobby Accessories & Tools",
        "keywords": "miniature painting tools, hobby accessories, airbrush miniatures, basing materials",
        "brief": "Hobby tools and accessories. Cover: airbrushes, paint sets, basing materials, display cases. Mention what beginners need vs advanced tools."
    },
}

SYSTEM_PROMPT = """You are a knowledgeable hobby expert writing SEO-optimised collection descriptions for CastForge, a premium resin miniature store. Write in a warm, authoritative tone — like a seasoned hobbyist helping others discover great products. Never use salesy language or exclamation marks. Use British English spelling.

Format: HTML with <p>, <h3>, <ul>, <li> tags only. No <h1> or <h2> — those are reserved for the page title. No images. No links. 300-500 words."""


def generate_description(collection_info, api_key):
    """Generate collection SEO description via Claude Haiku."""
    prompt = f"""Write an SEO-optimised collection description for "{collection_info['title']}".

Target keywords: {collection_info['keywords']}
Brief: {collection_info['brief']}

Remember: 300-500 words, HTML format (<p>, <h3>, <ul>, <li> only), warm expert tone, British English."""

    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 2000,
                  "system": SYSTEM_PROMPT,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60)
        if r.status_code == 200:
            import re
            text = r.json()["content"][0]["text"].strip()
            text = re.sub(r"^```html?\s*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text)
            return text.strip()
    except Exception as e:
        print(f"    Generation error: {e}")
    return None


def main():
    api_key = config.ANTHROPIC_API_KEY
    token = get_shopify_token()
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    # Fetch all custom collections + smart collections
    print("\n  Generating collection SEO descriptions\n")

    all_collections = []
    for endpoint in ["custom_collections", "smart_collections"]:
        url = f"{base}/{endpoint}.json?limit=250"
        while url:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                break
            data = r.json()
            all_collections.extend(data.get(endpoint, []))
            # Pagination
            link = r.headers.get("Link", "")
            url = None
            if 'rel="next"' in link:
                for part in link.split(", <"):
                    if 'rel="next"' in part:
                        url = part.split(">")[0].lstrip("<")
                        break

    # Build handle → id map
    handle_map = {}
    for c in all_collections:
        handle_map[c["handle"]] = c["id"]

    print(f"  Found {len(all_collections)} collections on Shopify\n")

    updated = 0
    skipped = 0

    for handle, info in COLLECTIONS.items():
        cid = handle_map.get(handle)
        if not cid:
            print(f"  [{handle}] not found on Shopify — skipping")
            skipped += 1
            continue

        print(f"  [{handle}] generating...", end=" ", flush=True)
        body = generate_description(info, api_key)
        if not body:
            print("FAILED")
            continue

        # Determine collection type
        is_smart = any(c["handle"] == handle and c.get("rules") is not None
                       for c in all_collections)
        endpoint = "smart_collections" if is_smart else "custom_collections"

        # Update collection body_html
        r = requests.put(f"{base}/{endpoint}/{cid}.json", headers=headers, json={
            endpoint.rstrip("s"): {"id": cid, "body_html": body}
        }, timeout=15)

        if r.status_code == 200:
            print(f"✓ ({len(body)} chars)")
            updated += 1
        else:
            print(f"error {r.status_code}")

        time.sleep(1.5)  # Rate limit

    print(f"\n  Done! {updated} collections updated, {skipped} not found.\n")


if __name__ == "__main__":
    main()
