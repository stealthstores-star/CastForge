#!/usr/bin/env python3
"""
Set up smart collections (New Arrivals, Best Sellers) + tag featured products.

Usage: python3 setup_smart_collections.py
"""
import json, random, re, sys, time
from pathlib import Path
import requests
import config
from uploader import get_shopify_token

def main():
    token = get_shopify_token()
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    print("\n  Setting up smart collections + featured tags\n")

    # 1. Create New Arrivals smart collection
    print("  Creating 'New Arrivals' smart collection...")
    r = requests.post(f"{base}/smart_collections.json", headers=headers, json={
        "smart_collection": {
            "title": "New Arrivals",
            "handle": "new-arrivals",
            "rules": [{"column": "created_at", "relation": "less_than", "condition": "60"}],
            "sort_order": "created-desc",
            "published": True,
            "body_html": "<p>The latest additions to our resin model collection. Fresh arrivals added weekly.</p>"
        }
    }, timeout=15)
    if r.status_code in (200, 201):
        print(f"    ✓ Created (ID: {r.json()['smart_collection']['id']})")
    elif r.status_code == 422 and "already" in r.text.lower():
        print(f"    Already exists")
    else:
        print(f"    {r.status_code}: {r.text[:100]}")

    time.sleep(1)

    # 2. Create Best Sellers smart collection (tag-based)
    print("  Creating 'Best Sellers' smart collection...")
    r = requests.post(f"{base}/smart_collections.json", headers=headers, json={
        "smart_collection": {
            "title": "Best Sellers",
            "handle": "best-sellers",
            "rules": [{"column": "tag", "relation": "equals", "condition": "featured"}],
            "sort_order": "best-selling",
            "published": True,
            "body_html": "<p>Our most popular resin models, chosen by collectors worldwide.</p>"
        }
    }, timeout=15)
    if r.status_code in (200, 201):
        print(f"    ✓ Created (ID: {r.json()['smart_collection']['id']})")
    elif r.status_code == 422 and "already" in r.text.lower():
        print(f"    Already exists")
    else:
        print(f"    {r.status_code}: {r.text[:100]}")

    time.sleep(1)

    # 3. Tag 100 products as "featured" from visual categories
    print("\n  Tagging 100 products as 'featured' for Best Sellers...")
    col_map = json.loads(Path("collection_map.json").read_text()) if Path("collection_map.json").exists() else {}

    featured_handles = ["wargaming-heroes-characters", "busts-portraits", "fantasy-warriors",
                        "scifi-figures", "anime-characters", "scale-military-vehicles"]
    all_candidates = []

    for handle in featured_handles:
        col_id = col_map.get(handle)
        if not col_id:
            continue
        r = requests.get(f"{base}/collections/{col_id}/products.json?limit=30&fields=id,title,images,tags",
            headers=headers, timeout=15)
        if r.status_code == 200:
            prods = r.json().get("products", [])
            # Prefer products WITH images
            with_img = [p for p in prods if p.get("images")]
            all_candidates.extend(with_img[:20])
        time.sleep(0.5)

    print(f"    Found {len(all_candidates)} candidates across {len(featured_handles)} collections")

    # Shuffle and tag up to 100
    random.shuffle(all_candidates)
    tagged = 0
    for p in all_candidates[:100]:
        pid = p["id"]
        existing_tags = [t.strip() for t in (p.get("tags", "") or "").split(",") if t.strip()]
        if "featured" in existing_tags:
            tagged += 1
            continue
        existing_tags.append("featured")
        try:
            r = requests.put(f"{base}/products/{pid}.json", headers=headers,
                json={"product": {"id": pid, "tags": ", ".join(existing_tags)}}, timeout=15)
            if r.status_code in (200, 201):
                tagged += 1
        except Exception:
            pass
        time.sleep(0.3)
        if tagged % 20 == 0:
            print(f"    ...{tagged} tagged", flush=True)

    print(f"    ✓ {tagged} products tagged as 'featured'\n")

    # 4. Verify collections populated
    time.sleep(2)
    for handle in ["new-arrivals", "best-sellers"]:
        r = requests.get(f"{base}/smart_collections.json?handle={handle}", headers=headers, timeout=15)
        if r.status_code == 200:
            cols = r.json().get("smart_collections", [])
            if cols:
                col_id = cols[0]["id"]
                cr = requests.get(f"{base}/smart_collections/{col_id}/products/count.json", headers=headers, timeout=15)
                count = cr.json().get("count", 0) if cr.status_code == 200 else "?"
                print(f"  {handle}: {count} products")

    print("\n  Done!\n")

if __name__ == "__main__":
    main()
