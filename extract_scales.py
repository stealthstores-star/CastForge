#!/usr/bin/env python3
"""
Extract all scale tokens from product titles across the store.
Outputs scales.json: [{scale: "1/35", count: 3820, slug: "1-35"}, ...]

Usage: python3 extract_scales.py
"""
import json, re, time
from pathlib import Path
from collections import Counter
import requests, config
from uploader import get_shopify_token

def fetch_all_titles(token):
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"
    titles = []
    url = f"{base}/products.json?limit=250&fields=id,title&status=active"
    while url:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 2))); continue
        if r.status_code != 200: break
        for p in r.json().get("products", []):
            titles.append((p["id"], p.get("title", "")))
        if len(titles) % 2000 < 250:
            print(f"  ...{len(titles)} titles", flush=True)
        url = None
        link = r.headers.get("Link", "")
        for part in link.split(", <"):
            if 'rel="next"' in part:
                url = part.split(">")[0].lstrip("<"); break
        time.sleep(0.5)
    return titles

def extract_scale(title):
    """Extract scale tokens from title."""
    scales = set()
    # 1/35, 1/72, 1:35 etc
    for m in re.finditer(r'\b1[/:](\d{1,4})\b', title):
        scales.add(f"1/{m.group(1)}")
    # 75mm, 28mm, 54mm etc
    for m in re.finditer(r'\b(\d{2,3})mm\b', title, re.IGNORECASE):
        scales.add(f"{m.group(1)}mm")
    return scales

def main():
    token = get_shopify_token()
    print("\n  Extracting scales from all product titles...\n")
    titles = fetch_all_titles(token)
    print(f"  {len(titles)} products fetched\n")

    counter = Counter()
    product_scales = {}  # pid → set of scales

    for pid, title in titles:
        scales = extract_scale(title)
        for s in scales:
            counter[s] += 1
        if scales:
            product_scales[pid] = list(scales)

    # Filter: only scales with ≥5 products
    result = []
    for scale, count in counter.most_common():
        if count < 5:
            continue
        slug = scale.replace("/", "-").lower()
        result.append({"scale": scale, "count": count, "slug": slug})

    Path("scales.json").write_text(json.dumps(result, indent=2))
    Path("product_scales.json").write_text(json.dumps(product_scales, indent=2))

    print(f"  Scales found (≥5 products):")
    for s in result:
        print(f"    {s['scale']:8s} → {s['count']:5d} products (slug: {s['slug']})")
    print(f"\n  Saved: scales.json ({len(result)} scales), product_scales.json ({len(product_scales)} products)")
    print(f"  Next: python3 tag_scales.py\n")

if __name__ == "__main__":
    main()
