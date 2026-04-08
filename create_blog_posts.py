#!/usr/bin/env python3
"""
Create 10 SEO-optimized blog posts via Claude Haiku + Shopify API.
Each post targets long-tail keywords for organic search traffic.

Usage: python3 create_blog_posts.py
"""
import json, sys, time
import requests
import config
from uploader import get_shopify_token

POSTS = [
    {
        "title": "Best 1/35 Scale WWII Tank Models for Beginners",
        "tags": "scale-models, 1/35, wwii, tanks, beginners",
        "prompt": "Write a 1500-word blog post titled 'Best 1/35 Scale WWII Tank Models for Beginners'. Cover: why 1/35 is the best scale for first-time builders, top 5 tank models to start with (Tiger I, Sherman, T-34, Panzer IV, Churchill), what tools you need, assembly tips for resin vs plastic, painting basics. Include internal links to /collections/scale-military-vehicles and /pages/scale-guide. Tone: knowledgeable hobbyist helping a newcomer, not salesy. HTML format with h2, h3, p, ul tags."
    },
    {
        "title": "How to Paint Resin Miniatures: Complete Guide for 2025",
        "tags": "painting, resin, tutorial, beginners",
        "prompt": "Write a 1800-word blog post titled 'How to Paint Resin Miniatures: Complete Guide for 2025'. Cover: preparing resin (washing, mold line removal, pinning), priming (which primers work on resin), basecoating, layering, washing, drybrushing, highlighting, varnishing. Mention Vallejo and Citadel paint ranges. Include tips for common mistakes. Link to /collections/accessories and /pages/scale-guide. HTML format."
    },
    {
        "title": "1/72 vs 1/35 Scale: Which Is Right for You?",
        "tags": "scale-guide, 1/72, 1/35, comparison",
        "prompt": "Write a 1200-word blog post comparing 1/72 and 1/35 scale models. Cover: size difference (with measurements), detail level, price points, storage space, painting difficulty, diorama building, wargaming compatibility, display options. Include a comparison table. Help reader choose based on their goals. Link to /collections/scale-military-vehicles and /pages/scale-guide. HTML format."
    },
    {
        "title": "Top 20 Warhammer-Compatible Resin Alternatives in 2025",
        "tags": "wargaming, warhammer, alternatives, resin",
        "prompt": "Write a 1500-word blog post about resin miniature alternatives to Games Workshop models. Cover: why hobbyists look for alternatives (price, variety, unique sculpts), 20 categories of compatible minis (infantry, heroes, vehicles, monsters, terrain), scale compatibility (28mm/32mm), legal considerations, quality comparison. Don't badmouth GW — position alternatives as expanding options. Link to /collections/wargaming-infantry and /collections/wargaming-heroes-characters. HTML format."
    },
    {
        "title": "How to Build Your First Wargaming Diorama",
        "tags": "diorama, terrain, tutorial, beginners",
        "prompt": "Write a 1400-word blog post guiding beginners through building their first diorama. Cover: choosing a scene/theme, selecting a base, building terrain (foam, plaster, real earth), adding miniatures, painting the environment, vegetation and water effects, weathering, final presentation. Include a materials list. Link to /collections/terrain-buildings-ruins and /collections/terrain-natural. HTML format."
    },
    {
        "title": "Resin vs Plastic Miniatures: The Honest Comparison",
        "tags": "resin, plastic, comparison, materials",
        "prompt": "Write a 1300-word blog post honestly comparing resin and plastic miniatures. Cover: detail quality, material properties, assembly difficulty, painting surface quality, price, durability, availability, environmental considerations. Be balanced but explain why serious collectors and painters prefer resin. Link to /pages/faq and /collections/all. HTML format."
    },
    {
        "title": "Cleaning and Prepping Resin Models Before Painting",
        "tags": "resin, preparation, tutorial",
        "prompt": "Write a 1200-word blog post about preparing resin models for painting. Cover: why washing is essential (mold release agent), washing method (warm soapy water, soft brush), removing flash and mold lines (hobby knife, files), filling gaps (milliput, green stuff), pinning for strength, dry fitting, priming. Common mistakes to avoid. Link to /collections/accessories and /pages/faq. HTML format."
    },
    {
        "title": "Best Airbrush for Resin Miniatures Under $100",
        "tags": "airbrush, tools, painting, budget",
        "prompt": "Write a 1400-word blog post reviewing the best affordable airbrushes for miniature painting. Cover: why airbrush matters for resin (smooth primer, zenithal highlighting, glazes), 5 budget options under $100 with pros/cons, compressor requirements, essential accessories, maintenance basics, first projects to try. Link to /collections/accessories. HTML format."
    },
    {
        "title": "Historical Accuracy in Scale Modeling: How Much Matters?",
        "tags": "historical, accuracy, scale-models",
        "prompt": "Write a 1300-word blog post discussing historical accuracy in scale modeling. Cover: the spectrum from 'looks cool' to rivet-counting, common accuracy debates (camo patterns, unit markings, equipment), research resources (books, photos, forums), when accuracy matters vs artistic license, competition judging criteria. Balanced — don't gatekeep. Link to /collections/scale-military-vehicles and /collections/scale-aircraft. HTML format."
    },
    {
        "title": "Understanding Resin Model Scales: Complete Chart & Guide",
        "tags": "scales, guide, reference, beginners",
        "prompt": "Write a 1500-word comprehensive guide to miniature scales. Cover every common scale from 1/6 to 1/700 with: actual size of a human figure at that scale, what it's used for, popular product types, compatibility with game systems. Include a reference table. Explain mm scales (28mm, 75mm, 120mm). Help readers understand what they're buying. Link to /pages/scale-guide and /collections/all. HTML format."
    },
]

def generate_post(prompt, api_key):
    """Generate blog post content via Claude Haiku."""
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 4000,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60)
        if r.status_code == 200:
            text = r.json()["content"][0]["text"].strip()
            # Strip code fences
            import re
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

    # Ensure blog exists
    print("\n  Creating blog posts (10 SEO articles)\n")
    r = requests.get(f"{base}/blogs.json", headers=headers, timeout=15)
    blogs = r.json().get("blogs", []) if r.status_code == 200 else []
    blog_id = None
    for b in blogs:
        if b.get("handle") == "news":
            blog_id = b["id"]
            break
    if not blog_id:
        r = requests.post(f"{base}/blogs.json", headers=headers,
            json={"blog": {"title": "News & Guides", "handle": "news"}}, timeout=15)
        if r.status_code in (200, 201):
            blog_id = r.json()["blog"]["id"]
    if not blog_id:
        print("  Could not find or create blog"); return

    for i, post in enumerate(POSTS):
        print(f"  [{i+1}/{len(POSTS)}] {post['title']}...", end=" ", flush=True)

        # Generate content
        body = generate_post(post["prompt"], api_key)
        if not body:
            print("FAILED to generate")
            continue

        # Create article
        r = requests.post(f"{base}/blogs/{blog_id}/articles.json", headers=headers, json={
            "article": {
                "title": post["title"],
                "body_html": body,
                "tags": post["tags"],
                "published": True,
                "author": "CastForge Team"
            }
        }, timeout=15)

        if r.status_code in (200, 201):
            handle = r.json()["article"].get("handle", "")
            print(f"✓ /blogs/news/{handle}")
        elif r.status_code == 422:
            print(f"already exists")
        else:
            print(f"error {r.status_code}")

        time.sleep(2)  # Rate limit between Haiku calls

    print(f"\n  Done! All blog posts created.\n")

if __name__ == "__main__":
    main()
