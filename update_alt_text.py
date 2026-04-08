#!/usr/bin/env python3
"""
Update image alt text for all products.

Format: "{product title} - {scale} resin model"
Skips images that already have alt text.
Resumable via progress file.

Usage: python3 update_alt_text.py
"""
import json, re, time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import config
from uploader import get_shopify_token

PROGRESS_FILE = "alt_text_progress.json"


def make_session():
    """Create a requests.Session with automatic retry on connection errors."""
    s = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=2,            # 2, 4, 8, 16, 32s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "PUT", "POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def extract_scale(product):
    """Extract scale from product tags or title."""
    for tag in product.get("tags", "").split(", "):
        tag = tag.strip()
        if tag.startswith("scale:"):
            return tag.replace("scale:", "").replace("-", "/")
    m = re.search(r'(1/\d+|1:\d+|\d+mm)', product.get("title", ""), re.I)
    if m:
        return m.group(1)
    return None


def load_progress():
    try:
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"done_ids": []}


def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)


def main():
    token = get_shopify_token()
    session = make_session()
    session.headers.update({
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": token,
    })
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    progress = load_progress()
    done_ids = set(progress["done_ids"])

    print("\n  Updating image alt text\n")

    url = f"{base}/products.json?limit=250&fields=id,title,tags,images"
    total_updated = 0
    total_skipped = 0

    while url:
        r = session.get(url, timeout=30)
        if r.status_code != 200:
            print(f"  API error: {r.status_code}")
            break

        products = r.json().get("products", [])
        for p in products:
            pid = p["id"]
            if pid in done_ids:
                continue

            scale = extract_scale(p)
            title = p["title"]
            alt_base = f"{title} - {scale} resin model" if scale else f"{title} - resin model"

            images_to_update = []
            for img in p.get("images", []):
                if img.get("alt") and img["alt"].strip():
                    continue
                images_to_update.append(img)

            if not images_to_update:
                done_ids.add(pid)
                total_skipped += 1
                continue

            for img in images_to_update:
                alt = alt_base if len(images_to_update) == 1 else f"{alt_base} view {img.get('position', 1)}"
                r2 = session.put(
                    f"{base}/products/{pid}/images/{img['id']}.json",
                    json={"image": {"id": img["id"], "alt": alt}},
                    timeout=30,
                )
                if r2.status_code == 200:
                    total_updated += 1
                else:
                    print(f"  [{pid}] image {img['id']} error: {r2.status_code}")
                time.sleep(0.5)

            done_ids.add(pid)
            progress["done_ids"] = list(done_ids)
            save_progress(progress)

            if total_updated % 50 == 0 and total_updated > 0:
                print(f"  ... {total_updated} images updated, {total_skipped} products skipped")

        # Pagination
        link = r.headers.get("Link", "")
        url = None
        if 'rel="next"' in link:
            for part in link.split(", <"):
                if 'rel="next"' in part:
                    url = part.split(">")[0].lstrip("<")
                    break

    progress["done_ids"] = list(done_ids)
    save_progress(progress)
    print(f"\n  Done! {total_updated} images updated, {total_skipped} products already had alt text.\n")


if __name__ == "__main__":
    main()
