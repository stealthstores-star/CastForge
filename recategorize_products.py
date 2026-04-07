#!/usr/bin/env python3
"""
Re-categorise all Shopify products using the updated categorizer.
Moves products to correct collections if category changed.

Usage:
    python3 recategorize_products.py              # Full run
    python3 recategorize_products.py --dry-run     # Show changes without applying
    python3 recategorize_products.py --limit 50    # First 50 unprocessed
"""
import json, sys, time
from pathlib import Path

import requests
import config
from categorizer import categorize
from uploader import get_shopify_token

PROGRESS_FILE = Path("recat_progress.json")
LOG_FILE = Path("recategorized.json")
COLLECTION_MAP_FILE = Path("collection_map.json")

def shopify_headers(token):
    return {"Content-Type": "application/json", "X-Shopify-Access-Token": token}

def shopify_base():
    return f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

def fetch_all_products(token):
    headers = shopify_headers(token)
    products = []
    for status in ["active", "draft"]:
        url = f"{shopify_base()}/products.json?limit=250&fields=id,title,tags,status&status={status}"
        while url:
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 2)))
                continue
            if r.status_code != 200:
                break
            products.extend(r.json().get("products", []))
            if len(products) % 1000 < 250:
                print(f"    ...{len(products)} fetched", flush=True)
            url = None
            link = r.headers.get("Link", "")
            if 'rel="next"' in link:
                for part in link.split(","):
                    if 'rel="next"' in part:
                        url = part.split("<")[1].split(">")[0]
            time.sleep(0.5)
    return products

def load_progress():
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {"processed_ids": []}

def save_progress(progress):
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2))

def main():
    dry_run = "--dry-run" in sys.argv
    limit = None
    for i, a in enumerate(sys.argv):
        if a == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])

    token = get_shopify_token()
    headers = shopify_headers(token)
    base = shopify_base()

    collection_map = {}
    if COLLECTION_MAP_FILE.exists():
        collection_map = json.loads(COLLECTION_MAP_FILE.read_text())

    print(f"\n══════════════════════════════════════")
    print(f"  CastForge Re-Categoriser")
    print(f"══════════════════════════════════════")
    print(f"  Collections: {len(collection_map)}")
    print(f"  Dry run: {dry_run}\n")

    print("  Fetching products...")
    products = fetch_all_products(token)
    print(f"  Found {len(products)} products\n")

    progress = load_progress()
    processed_set = set(progress["processed_ids"])
    todo = [p for p in products if p["id"] not in processed_set]
    if limit:
        todo = todo[:limit]
    print(f"  Already processed: {len(processed_set)}")
    print(f"  To process: {len(todo)}\n")

    moved = 0
    unchanged = 0
    log_entries = []
    if LOG_FILE.exists():
        log_entries = json.loads(LOG_FILE.read_text())

    for i, p in enumerate(todo):
        pid = p["id"]
        title = p.get("title", "")
        existing_tags = [t.strip() for t in (p.get("tags", "") or "").split(",") if t.strip()]

        # Find current category from tags
        current_cat = None
        for tag in existing_tags:
            if tag in collection_map:
                current_cat = tag
                break

        # Re-categorise
        new_cat, _, new_parent = categorize(title)

        if new_cat and new_cat != current_cat:
            moved += 1
            if dry_run:
                print(f"  [{i+1}/{len(todo)}] MOVE: {current_cat} → {new_cat} | {title[:60]}")
            else:
                # Update tags
                new_tags = [t for t in existing_tags if t not in collection_map]
                if new_cat:
                    new_tags.append(new_cat)
                if new_parent:
                    new_tags.append(new_parent)
                try:
                    requests.put(f"{base}/products/{pid}.json", headers=headers,
                        json={"product": {"id": pid, "tags": ", ".join(new_tags)}}, timeout=15)
                except Exception:
                    pass

                # Assign to new collections
                for handle in [new_cat, new_parent]:
                    if handle and handle in collection_map:
                        try:
                            requests.post(f"{base}/collects.json", headers=headers,
                                json={"collect": {"product_id": pid, "collection_id": collection_map[handle]}},
                                timeout=15)
                        except Exception:
                            pass
                        time.sleep(0.3)

                print(f"  [{i+1}/{len(todo)}] MOVED: {current_cat} → {new_cat} | {title[:60]}")
                log_entries.append({"id": pid, "title": title, "from": current_cat, "to": new_cat,
                                    "time": time.strftime("%Y-%m-%dT%H:%M:%S")})
                LOG_FILE.write_text(json.dumps(log_entries, indent=2, ensure_ascii=False))
        else:
            unchanged += 1

        progress["processed_ids"].append(pid)
        save_progress(progress)

        if (i + 1) % 100 == 0:
            print(f"  [{i+1}/{len(todo)}] moved={moved} unchanged={unchanged}")

        time.sleep(0.3)

    print(f"\n  Done: {moved} moved, {unchanged} unchanged\n")

if __name__ == "__main__":
    main()
