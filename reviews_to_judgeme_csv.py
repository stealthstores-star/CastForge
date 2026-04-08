#!/usr/bin/env python3
"""
Convert scraped AliExpress reviews to Judge.me CSV import format.
Pure local JSON → CSV, no API calls to AliExpress or Playwright.

Usage: python3 reviews_to_judgeme_csv.py
Output: judgeme_reviews.csv
"""
import csv, json, re, sys
from pathlib import Path

import requests
import config
from uploader import get_shopify_token

CHECKPOINT_FILE = Path("scrape_checkpoint.json")
PUSHED_TITLES_FILE = Path("pushed_titles.json")
REVIEWS_PROGRESS_FILE = Path("reviews_progress.json")
OUTPUT_FILE = Path("judgeme_reviews.csv")


def build_ali_to_handle():
    """Build {aliexpress_product_id → shopify_handle} mapping."""
    print("  Building AliExpress ID → Shopify handle mapping...")

    # Load pushed titles: {shopify_pid → {title, raw_title}}
    pushed = json.loads(PUSHED_TITLES_FILE.read_text()) if PUSHED_TITLES_FILE.exists() else {}

    # Load checkpoint for ali_id → raw_title mapping
    cp = json.loads(CHECKPOINT_FILE.read_text()) if CHECKPOINT_FILE.exists() else {"products": []}
    ali_to_raw = {}
    for p in cp.get("products", []):
        url = p.get("product_url", "")
        m = re.search(r"/item/(\d+)\.html", url)
        if m:
            ali_to_raw[m.group(1)] = p.get("product_title", "")

    # Build raw_title → shopify_pid
    raw_to_spid = {}
    for spid, data in pushed.items():
        raw = data.get("raw_title", "")
        if raw:
            raw_to_spid[raw] = spid

    # Now get handles from Shopify for the matched product IDs
    spids_needed = set(raw_to_spid.values())
    print(f"  {len(spids_needed)} Shopify products to look up handles for...")

    token = get_shopify_token()
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    # Fetch all products with handles
    spid_to_handle = {}
    for status in ["active", "draft"]:
        url = f"{base}/products.json?limit=250&fields=id,handle&status={status}"
        while url:
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code == 429:
                import time; time.sleep(float(r.headers.get("Retry-After", 2))); continue
            if r.status_code != 200: break
            for p in r.json().get("products", []):
                spid_to_handle[str(p["id"])] = p["handle"]
            if len(spid_to_handle) % 2000 < 250:
                print(f"    ...{len(spid_to_handle)} handles fetched", flush=True)
            url = None
            link = r.headers.get("Link", "")
            for part in link.split(", <"):
                if 'rel="next"' in part:
                    url = part.split(">")[0].lstrip("<"); break
            import time; time.sleep(0.5)

    print(f"  {len(spid_to_handle)} handles fetched from Shopify")

    # Final mapping: ali_id → handle
    ali_to_handle = {}
    for ali_id, raw_title in ali_to_raw.items():
        spid = raw_to_spid.get(raw_title)
        if spid and spid in spid_to_handle:
            ali_to_handle[ali_id] = spid_to_handle[spid]

    print(f"  {len(ali_to_handle)} AliExpress IDs mapped to Shopify handles")
    return ali_to_handle


def load_reviews():
    """Load reviews from reviews_progress.json or scrape_checkpoint.json reviews cache."""
    # reviews_progress.json tracks which products were processed
    # The actual review data lives in the Shopify metafields or was stored during scraping
    # Check if we have a local reviews cache
    reviews_cache = Path("reviews_cache.json")
    if reviews_cache.exists():
        return json.loads(reviews_cache.read_text())

    # Try to reconstruct from pull_reviews.py output
    # The pull_reviews script stores reviews in Shopify metafields, not locally
    # We need to pull them back from Shopify
    print("  No local reviews cache found. Pulling from Shopify metafields...")

    token = get_shopify_token()
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    progress = json.loads(REVIEWS_PROGRESS_FILE.read_text()) if REVIEWS_PROGRESS_FILE.exists() else {"processed_ids": []}
    processed = progress.get("processed_ids", [])

    reviews_by_product = {}
    for i, spid in enumerate(processed):
        try:
            r = requests.get(f"{base}/products/{spid}/metafields.json?namespace=reviews",
                headers=headers, timeout=15)
            if r.status_code == 200:
                for mf in r.json().get("metafields", []):
                    if mf.get("key") == "aliexpress":
                        val = mf.get("value", "")
                        if val:
                            reviews_by_product[str(spid)] = json.loads(val) if isinstance(val, str) else val
        except Exception:
            pass

        if (i + 1) % 100 == 0:
            print(f"    ...{i+1}/{len(processed)} checked", flush=True)
        import time; time.sleep(0.3)

    # Save cache for next time
    reviews_cache.write_text(json.dumps(reviews_by_product, indent=2, ensure_ascii=False))
    print(f"  {len(reviews_by_product)} products with reviews cached to reviews_cache.json")
    return reviews_by_product


def main():
    print(f"\n  Converting reviews to Judge.me CSV format\n")

    ali_to_handle = build_ali_to_handle()

    # Load checkpoint to map shopify_pid back to ali_id
    cp = json.loads(CHECKPOINT_FILE.read_text()) if CHECKPOINT_FILE.exists() else {"products": []}
    pushed = json.loads(PUSHED_TITLES_FILE.read_text()) if PUSHED_TITLES_FILE.exists() else {}

    # Build spid → ali_id reverse map
    spid_to_ali = {}
    for ali_id, handle in ali_to_handle.items():
        # Find spid for this ali_id
        for p in cp.get("products", []):
            m = re.search(r"/item/(\d+)\.html", p.get("product_url", ""))
            if m and m.group(1) == ali_id:
                raw = p.get("product_title", "")
                for spid, data in pushed.items():
                    if data.get("raw_title") == raw:
                        spid_to_ali[spid] = ali_id
                        break
                break

    # Also build spid → handle
    spid_to_handle = {}
    for spid in pushed:
        ali_id = spid_to_ali.get(spid)
        if ali_id and ali_id in ali_to_handle:
            spid_to_handle[spid] = ali_to_handle[ali_id]

    # Load reviews (keyed by shopify product ID)
    reviews_by_spid = load_reviews()
    print(f"  {len(reviews_by_spid)} products have reviews")

    # Write CSV
    rows = []
    for spid, reviews in reviews_by_spid.items():
        handle = spid_to_handle.get(spid)
        if not handle:
            # Try direct lookup
            continue
        if not isinstance(reviews, list):
            continue

        # Sort: 5★+images > 5★ text > 4★+images > 4★
        reviews.sort(key=lambda r: (-(r.get("rating", 0)), -int(bool(r.get("images")))))

        for rev in reviews[:12]:
            body = (rev.get("text") or "").strip()
            if not body or len(body) < 10:
                continue
            rating = rev.get("rating", 5)
            if rating < 4:
                continue

            title = body[:50].rstrip() + ("..." if len(body) > 50 else "")
            date = rev.get("date", "")
            if not re.match(r"\d{4}-\d{2}-\d{2}", date):
                date = "2025-01-01"  # fallback
            name = rev.get("name", "Verified Buyer")
            images = rev.get("images", [])
            pic_urls = ",".join(u for u in images if u.startswith("http"))

            rows.append({
                "title": title,
                "body": body,
                "rating": rating,
                "review_date": date,
                "reviewer_name": name,
                "reviewer_email": "",
                "product_handle": handle,
                "picture_urls": pic_urls,
            })

    # Write CSV
    fieldnames = ["title", "body", "rating", "review_date", "reviewer_name",
                  "reviewer_email", "product_handle", "picture_urls"]
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n  Done! {len(rows)} reviews → {OUTPUT_FILE}")
    print(f"  Products with reviews: {len(reviews_by_spid)}")
    print(f"  Upload to Judge.me: Settings → Import reviews → CSV\n")


if __name__ == "__main__":
    main()
