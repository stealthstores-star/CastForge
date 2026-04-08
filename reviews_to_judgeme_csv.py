#!/usr/bin/env python3
"""
Convert locally scraped AliExpress reviews to Judge.me CSV format.
Reads from reviews_progress.json (local data), NO Shopify metafield fetch.

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
REVIEWS_CACHE_FILE = Path("reviews_cache.json")
OUTPUT_FILE = Path("judgeme_reviews.csv")


def build_spid_to_handle():
    """Fetch all Shopify product handles. Returns {str(product_id): handle}."""
    print("  Fetching Shopify product handles...")
    token = get_shopify_token()
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"
    import time

    result = {}
    for status in ["active", "draft"]:
        url = f"{base}/products.json?limit=250&fields=id,handle&status={status}"
        while url:
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 2))); continue
            if r.status_code != 200: break
            for p in r.json().get("products", []):
                result[str(p["id"])] = p["handle"]
            if len(result) % 2000 < 250:
                print(f"    ...{len(result)}", flush=True)
            url = None
            link = r.headers.get("Link", "")
            for part in link.split(", <"):
                if 'rel="next"' in part:
                    url = part.split(">")[0].lstrip("<"); break
            time.sleep(0.5)
    print(f"  {len(result)} handles fetched")
    return result


def build_ali_to_spid():
    """Build {ali_product_id: shopify_product_id} from checkpoint + pushed_titles."""
    cp = json.loads(CHECKPOINT_FILE.read_text()) if CHECKPOINT_FILE.exists() else {"products": []}
    pushed = json.loads(PUSHED_TITLES_FILE.read_text()) if PUSHED_TITLES_FILE.exists() else {}

    # raw_title → spid
    raw_to_spid = {}
    for spid, data in pushed.items():
        raw = data.get("raw_title", "")
        if raw:
            raw_to_spid[raw] = spid

    # ali_id → spid
    ali_to_spid = {}
    for p in cp.get("products", []):
        m = re.search(r"/item/(\d+)\.html", p.get("product_url", ""))
        if not m:
            continue
        ali_id = m.group(1)
        raw = p.get("product_title", "")
        spid = raw_to_spid.get(raw)
        if spid:
            ali_to_spid[ali_id] = spid

    return ali_to_spid


def load_local_reviews():
    """Load reviews from local JSON files. Returns {key: [review_list]}."""
    reviews = {}

    # Try reviews_cache.json first (may have been saved by previous run)
    if REVIEWS_CACHE_FILE.exists():
        data = json.loads(REVIEWS_CACHE_FILE.read_text())
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list) and len(v) > 0:
                    reviews[k] = v
        if reviews:
            print(f"  Loaded {len(reviews)} products from reviews_cache.json")
            return reviews

    # Try reviews_progress.json — might contain review data
    if REVIEWS_PROGRESS_FILE.exists():
        data = json.loads(REVIEWS_PROGRESS_FILE.read_text())
        # Check structure: could be {processed_ids: [...]} or {pid: [reviews]}
        if isinstance(data, dict):
            # If it has review arrays as values (not just processed_ids)
            for k, v in data.items():
                if k == "processed_ids":
                    continue
                if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                    reviews[k] = v
        if reviews:
            print(f"  Loaded {len(reviews)} products from reviews_progress.json")
            return reviews

    # Try full_cleanup progress
    cleanup_progress = Path("cleanup_progress.json")
    if cleanup_progress.exists():
        data = json.loads(cleanup_progress.read_text())
        phase4 = data.get("phase4_reviews", [])
        if phase4:
            for entry in phase4:
                if isinstance(entry, dict) and "reviews" in entry:
                    reviews[str(entry.get("id", ""))] = entry["reviews"]
            if reviews:
                print(f"  Loaded {len(reviews)} products from cleanup_progress.json phase4")
                return reviews

    print("  No local review data found!")
    print("  Expected: reviews_cache.json or reviews_progress.json with review data")
    return reviews


def main():
    print(f"\n  Converting local reviews to Judge.me CSV\n")

    # Load local reviews
    reviews_data = load_local_reviews()
    if not reviews_data:
        print("  No reviews to convert. Run pull_reviews.py first.\n")
        return

    # Build mappings
    ali_to_spid = build_ali_to_spid()
    spid_to_handle = build_spid_to_handle()

    # Figure out what key type reviews_data uses (ali_id or spid)
    sample_key = next(iter(reviews_data))
    if len(sample_key) > 15:  # Likely AliExpress ID (long number)
        key_is_ali = True
        print(f"  Review keys look like AliExpress IDs")
    else:
        key_is_ali = False
        print(f"  Review keys look like Shopify product IDs")

    # Write CSV
    rows = []
    matched = 0
    unmatched = 0

    for key, revs in reviews_data.items():
        if not isinstance(revs, list):
            continue

        # Resolve to handle
        handle = None
        if key_is_ali:
            spid = ali_to_spid.get(key)
            if spid:
                handle = spid_to_handle.get(spid)
        else:
            handle = spid_to_handle.get(key)
            if not handle:
                handle = spid_to_handle.get(str(key))

        if not handle:
            unmatched += 1
            continue
        matched += 1

        # Sort: 5★+images > 5★ text > 4★+images > 4★
        revs.sort(key=lambda r: (-(r.get("rating", 0)), -int(bool(r.get("images")))))

        for rev in revs[:12]:
            body = (rev.get("text") or "").strip()
            if not body or len(body) < 10:
                continue
            rating = rev.get("rating", 5)
            if rating < 4:
                continue

            title = body[:50].rstrip() + ("..." if len(body) > 50 else "")
            date = rev.get("date", "")
            if not re.match(r"\d{4}-\d{2}-\d{2}", date):
                date = "2025-01-01"
            name = rev.get("name", "Verified Buyer")
            images = rev.get("images", [])
            pic_urls = ",".join(u for u in images if isinstance(u, str) and u.startswith("http"))

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

    fieldnames = ["title", "body", "rating", "review_date", "reviewer_name",
                  "reviewer_email", "product_handle", "picture_urls"]
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n  {len(rows)} reviews → {OUTPUT_FILE}")
    print(f"  Products matched: {matched}, unmatched: {unmatched}")
    print(f"  Upload: Judge.me → Settings → Import → CSV\n")


if __name__ == "__main__":
    main()
