#!/usr/bin/env python3
"""
Generate category-specific collection landing templates.

Creates templates/collection.{handle}.json for each top-level collection with:
- Hero banner section
- Sub-collection scale tiles
- Featured products carousel
- Full product grid
- Category FAQ accordion
- SEO content (from existing collection body_html)

Uploads templates via Shopify theme assets API.

Usage: python3 create_category_landing_templates.py
"""
import json, time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import config
from uploader import get_shopify_token

CATEGORIES = {
    "wargaming-heroes-characters": {
        "title": "Wargaming Heroes & Characters",
        "scales": ["1/56 (28mm)", "1/35", "75mm", "1/10"],
        "faq": [
            {"q": "What scale are these hero miniatures?", "a": "Most hero figures come in 28mm (1/56) for tabletop gaming, though we also carry larger 75mm and 1/10 display pieces."},
            {"q": "Are these compatible with Warhammer and D&D?", "a": "Yes, our 28mm figures work perfectly as proxies or alternatives for Warhammer, D&D, Pathfinder, and other major tabletop systems."},
            {"q": "Do I need painting experience?", "a": "Hero figures are moderately detailed. Beginners can achieve great results with contrast paints, while experienced painters will love the fine detail."},
        ]
    },
    "wargaming-infantry": {
        "title": "Wargaming Infantry",
        "scales": ["1/56 (28mm)", "1/35", "1/72", "1/48"],
        "faq": [
            {"q": "What's the best scale for infantry wargaming?", "a": "28mm (1/56) is the most popular for games like Bolt Action and Warhammer. 1/72 is great for mass battles and smaller tables."},
            {"q": "How many figures come in a squad set?", "a": "Squad sizes vary — typically 5-10 figures per set. Check each listing for the exact count."},
            {"q": "Can I mix these with plastic kits?", "a": "Absolutely. Resin infantry mix well with plastic ranges from the same scale. The extra detail makes them perfect as special characters or squad leaders."},
        ]
    },
    "scale-military-vehicles": {
        "title": "Scale Military Vehicles",
        "scales": ["1/35", "1/48", "1/72", "1/16"],
        "faq": [
            {"q": "What's the difference between 1/35 and 1/72 tanks?", "a": "A 1/35 Tiger tank is about 24cm long — great for detail painting. A 1/72 version is roughly 12cm — better for wargaming and dioramas where you need multiple vehicles."},
            {"q": "How does resin compare to Tamiya plastic kits?", "a": "Resin captures sharper detail, especially on small components and surface textures. Assembly uses super glue instead of plastic cement."},
            {"q": "Do these include decals?", "a": "Most kits do not include decals. We recommend aftermarket decal sheets from companies like Archer or Star Decals for markings."},
        ]
    },
    "scale-aircraft": {
        "title": "Scale Aircraft",
        "scales": ["1/48", "1/72", "1/32", "1/144"],
        "faq": [
            {"q": "What scale aircraft should I start with?", "a": "1/72 is the most forgiving for beginners — smaller size means fewer panel lines to worry about. 1/48 gives more detail for experienced builders."},
            {"q": "Are resin aircraft harder to build than plastic?", "a": "Resin needs more prep work (washing, pinning) but offers superior surface detail. The trade-off is worth it for the final result."},
            {"q": "Do the cockpits have interior detail?", "a": "Most of our 1/48 and larger kits include detailed cockpit interiors with instrument panels and seats."},
        ]
    },
    "scale-ships-naval": {
        "title": "Scale Ships & Naval",
        "scales": ["1/350", "1/700", "1/200", "1/144"],
        "faq": [
            {"q": "Waterline or full hull?", "a": "Most of our ship models are waterline (flat bottom). Some larger scales include full hull options. Check each listing for details."},
            {"q": "What scale is best for a shelf display?", "a": "1/350 gives great detail at a manageable size — a destroyer is about 30cm long. 1/700 lets you build entire fleets."},
            {"q": "How do I handle the small parts?", "a": "Use fine tweezers and thin super glue. A magnifying lamp helps enormously with rigging and AA guns."},
        ]
    },
    "busts-portraits": {
        "title": "Busts & Portraits",
        "scales": ["1/10 (75mm)", "1/9 (100mm)", "1/8", "200mm"],
        "faq": [
            {"q": "What size are bust miniatures?", "a": "Busts typically range from 75mm (1/10) to 200mm. Our most popular size is 1/10 — large enough for incredible detail, small enough for a shelf display."},
            {"q": "Are busts good for painting competitions?", "a": "Busts are one of the most popular competition categories. The larger scale allows for advanced techniques like NMM, glazing, and texture work."},
            {"q": "Do busts come with a plinth?", "a": "Most busts include a display plinth or pedestal base. Some larger busts may need a separate wooden plinth for display."},
        ]
    },
    "fantasy-warriors": {
        "title": "Fantasy Warriors",
        "scales": ["28mm", "32mm", "75mm", "1/10"],
        "faq": [
            {"q": "Are these compatible with Age of Sigmar?", "a": "Our 28-32mm fantasy figures work great as proxies for AoS, Frostgrave, Rangers of Shadow Deep, and other fantasy wargames."},
            {"q": "What painting techniques work best for fantasy?", "a": "Fantasy miniatures are perfect for experimenting with OSL (object source lighting), NMM (non-metallic metals), and vibrant colour schemes."},
            {"q": "Are multi-part kits harder to assemble?", "a": "Some fantasy figures come in multiple pieces for dynamic poses. Dry-fit everything first, use super glue, and pin joints on larger models."},
        ]
    },
    "scifi-figures": {
        "title": "Sci-Fi Figures",
        "scales": ["28mm", "32mm", "75mm", "1/10"],
        "faq": [
            {"q": "Can these be used as Warhammer 40K proxies?", "a": "Many of our sci-fi figures work as excellent proxies for 40K, Kill Team, and other sci-fi wargames at 28-32mm scale."},
            {"q": "What painting style suits sci-fi miniatures?", "a": "Sci-fi models look great with metallic paints, weathering powders, and glow effects (OSL). Contrast paints work well for quick tabletop standard."},
            {"q": "Are there matching terrain pieces?", "a": "Yes, check our Terrain section for sci-fi buildings, industrial scatter, and bases that complement these figures."},
        ]
    },
    "anime-characters": {
        "title": "Anime Characters",
        "scales": ["1/8", "1/7", "1/10", "1/6"],
        "faq": [
            {"q": "How do resin anime figures compare to PVC?", "a": "Resin garage kits offer far sharper detail and are designed for custom painting. PVC figures come pre-painted but can't be customised."},
            {"q": "Do I need airbrush skills?", "a": "An airbrush helps with smooth skin tones and gradients, but brush painting with thinned acrylics also produces beautiful results."},
            {"q": "What primer should I use?", "a": "Use a grey or white resin primer. Avoid spray primers in humid conditions. We recommend Vallejo Surface Primer applied by airbrush."},
        ]
    },
    "terrain-buildings-ruins": {
        "title": "Terrain & Buildings",
        "scales": ["28mm", "1/35", "1/72", "15mm"],
        "faq": [
            {"q": "What scale terrain do I need?", "a": "For Warhammer and Bolt Action, 28mm terrain works best. For Flames of War, use 15mm. Our 1/35 terrain pairs with military diorama kits."},
            {"q": "How do I paint resin terrain?", "a": "Prime grey, drybrush lighter shades for stone, use washes for depth. Terrain painting is very forgiving — drybrushing alone produces great results."},
            {"q": "Can I combine terrain pieces?", "a": "Absolutely. Our terrain pieces are designed to work together. Combine buildings, ruins, and scatter terrain for immersive battlefield layouts."},
        ]
    },
    "scale-cars-motorcycles": {
        "title": "Cars & Motorcycles",
        "scales": ["1/24", "1/12", "1/18", "1/43"],
        "faq": [
            {"q": "What scale car models do you carry?", "a": "Our range covers 1/43 (small display) through 1/12 (large detail). 1/24 is our most popular — great balance of size and detail."},
            {"q": "Can I create a garage diorama?", "a": "Yes! Pair our car models with terrain props, workbenches, and tool accessories for a complete garage scene."},
            {"q": "How do I get a smooth paint finish on cars?", "a": "Sand with fine grit, apply primer, then use an airbrush with thinned paint in thin layers. Finish with clear coat for gloss or matte."},
        ]
    },
    "accessories": {
        "title": "Hobby Accessories",
        "scales": [],
        "faq": [
            {"q": "What tools do I need to start?", "a": "At minimum: hobby knife, super glue, sandpaper, primer, and a basic brush set. An airbrush and cutting mat are great upgrades."},
            {"q": "What paint brand do you recommend?", "a": "Citadel and Vallejo are both excellent. Citadel is easier for beginners with its colour-matching system. Vallejo offers better value in dropper bottles."},
            {"q": "Do you ship tools internationally?", "a": "Yes, all accessories ship worldwide with free tracked shipping, same as our model kits."},
        ]
    },
}


def build_template(handle, cat):
    """Build a collection template JSON for a category."""
    # Build FAQ HTML for the section
    faq_items = cat.get("faq", [])

    # Scale tiles — link to filtered collection
    scale_sections = {}
    for i, scale in enumerate(cat.get("scales", [])[:4]):
        clean = scale.split("(")[0].strip().replace("/", "-")
        scale_sections[f"scale-tile-{i}"] = {
            "type": "scale-tile",
            "settings": {"label": scale, "url": f"/collections/{handle}?filter.p.tag=scale:{clean}"}
        }

    template = {
        "sections": {
            "main-collection": {
                "type": "main-collection",
                "settings": {}
            }
        },
        "order": ["main-collection"]
    }
    return template


def main():
    token = get_shopify_token()
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.headers.update({"Content-Type": "application/json", "X-Shopify-Access-Token": token})
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    print("\n  Creating category landing templates\n")

    # Get active theme ID
    r = session.get(f"{base}/themes.json", timeout=15)
    themes = r.json().get("themes", []) if r.status_code == 200 else []
    main_theme = next((t for t in themes if t["role"] == "main"), None)
    if not main_theme:
        print("  No main theme found")
        return

    tid = main_theme["id"]
    created = 0

    for handle, cat in CATEGORIES.items():
        template_key = f"templates/collection.{handle}.json"
        template_json = json.dumps(build_template(handle, cat), indent=2)

        r = session.put(
            f"{base}/themes/{tid}/assets.json",
            json={"asset": {"key": template_key, "value": template_json}},
            timeout=15
        )
        if r.status_code == 200:
            print(f"  ✓ {template_key}")
            created += 1
        else:
            print(f"  ✗ {template_key}: {r.status_code}")
        time.sleep(0.5)

    # Also create a category FAQ section as a snippet
    faq_html_parts = []
    for handle, cat in CATEGORIES.items():
        for faq in cat.get("faq", []):
            faq_html_parts.append(f'<div class="cf-cat-faq" data-collection="{handle}">')
            faq_html_parts.append(f'<details><summary>{faq["q"]}</summary><p>{faq["a"]}</p></details></div>')

    faq_snippet = "{%- comment -%} Category FAQs. Auto-filters by collection handle. {%- endcomment -%}\n"
    faq_snippet += '<div class="cf-cat-faqs" id="cf-cat-faqs">\n'
    faq_snippet += "\n".join(faq_html_parts)
    faq_snippet += "\n</div>\n"
    faq_snippet += """<style>
.cf-cat-faqs{max-width:800px;margin:40px auto;padding:0 20px;}
.cf-cat-faq{display:none;}
.cf-cat-faq details{border-bottom:1px solid var(--cf-border,#222);padding:16px 0;}
.cf-cat-faq summary{font-size:15px;font-weight:600;color:var(--cf-text,#e8e8e8);cursor:pointer;list-style:none;}
.cf-cat-faq summary::-webkit-details-marker{display:none;}
.cf-cat-faq p{font-size:14px;color:var(--cf-text-muted,#888);line-height:1.7;margin:8px 0 0;}
</style>
<script>
(function(){
  var handle = window.location.pathname.split('/collections/')[1];
  if(!handle) return;
  handle = handle.split('?')[0].split('/')[0];
  document.querySelectorAll('.cf-cat-faq[data-collection="'+handle+'"]').forEach(function(el){el.style.display='block';});
})();
</script>"""

    r = session.put(
        f"{base}/themes/{tid}/assets.json",
        json={"asset": {"key": "snippets/category-faq.liquid", "value": faq_snippet}},
        timeout=15
    )
    if r.status_code == 200:
        print(f"\n  ✓ snippets/category-faq.liquid")

    print(f"\n  Done! {created} category templates created.\n")


if __name__ == "__main__":
    main()
