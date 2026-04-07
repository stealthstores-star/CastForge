#!/usr/bin/env python3
"""
Tag products with their scale (e.g. "scale:1-35", "scale:75mm").
Resumable via tag_scales_progress.json. Run after extract_scales.py.

Usage: python3 tag_scales.py
"""
import json, time
from pathlib import Path
import requests, config
from uploader import get_shopify_token

PROGRESS_FILE = Path("tag_scales_progress.json")
PRODUCT_SCALES_FILE = Path("product_scales.json")

def main():
    if not PRODUCT_SCALES_FILE.exists():
        print("Run extract_scales.py first"); return

    token = get_shopify_token()
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    product_scales = json.loads(PRODUCT_SCALES_FILE.read_text())
    progress = json.loads(PROGRESS_FILE.read_text()) if PROGRESS_FILE.exists() else {"done": []}
    done_set = set(progress["done"])

    todo = [(pid, scales) for pid, scales in product_scales.items() if int(pid) not in done_set]
    print(f"\n  Tagging scales on {len(todo)} products ({len(done_set)} already done)\n")

    tagged = 0
    for i, (pid, scales) in enumerate(todo):
        pid_int = int(pid)
        # Build scale tags
        new_tags = [f"scale:{s.replace('/', '-').lower()}" for s in scales]

        # Get current tags
        try:
            r = requests.get(f"{base}/products/{pid}.json?fields=id,tags", headers=headers, timeout=15)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 2)))
                r = requests.get(f"{base}/products/{pid}.json?fields=id,tags", headers=headers, timeout=15)
            if r.status_code != 200:
                continue
            existing = [t.strip() for t in (r.json()["product"].get("tags", "") or "").split(",") if t.strip()]
        except Exception:
            continue

        # Merge — don't duplicate
        merged = list(set(existing + new_tags))
        if set(merged) == set(existing):
            done_set.add(pid_int)
            progress["done"].append(pid_int)
            continue

        # Update
        try:
            ur = requests.put(f"{base}/products/{pid}.json", headers=headers,
                json={"product": {"id": pid_int, "tags": ", ".join(merged)}}, timeout=15)
            if ur.status_code == 429:
                time.sleep(float(ur.headers.get("Retry-After", 2)))
                ur = requests.put(f"{base}/products/{pid}.json", headers=headers,
                    json={"product": {"id": pid_int, "tags": ", ".join(merged)}}, timeout=15)
            if ur.status_code in (200, 201):
                tagged += 1
        except Exception:
            pass

        done_set.add(pid_int)
        progress["done"].append(pid_int)

        if (i + 1) % 100 == 0:
            PROGRESS_FILE.write_text(json.dumps(progress))
            print(f"  [{i+1}/{len(todo)}] tagged={tagged}")

        time.sleep(0.5)

    PROGRESS_FILE.write_text(json.dumps(progress))
    print(f"\n  Done: {tagged} products tagged with scale tags\n")

if __name__ == "__main__":
    main()
