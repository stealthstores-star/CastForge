#!/usr/bin/env python3
"""
Cleanup bad images from Shopify products.
Phase 1: Delete products with 0 images.
Phase 2: Vision-classify first image, delete emoji/clipart/non-product.

Usage:
    python3 cleanup_bad_images.py          # Both phases
    python3 cleanup_bad_images.py --phase1 # Only 0-image deletion
    python3 cleanup_bad_images.py --phase2 # Only vision classification
    python3 cleanup_bad_images.py --dry-run # Classify but don't delete
"""
import json, sys, time, threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import config
from uploader import get_shopify_token

PROGRESS_FILE = Path("cleanup_progress.json")
DELETED_0_FILE = Path("deleted_no_images_cleanup.json")
DELETED_BAD_FILE = Path("deleted_bad_image_cleanup.json")
SAFETY_LIMIT = 500

_file_lock = threading.Lock()

def shopify_headers(token):
    return {"Content-Type": "application/json", "X-Shopify-Access-Token": token}

def shopify_base():
    return f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

def fetch_all_products(token):
    headers = shopify_headers(token)
    products = []
    url = f"{shopify_base()}/products.json?limit=250&fields=id,title,images,status&status=active"
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
    # Also fetch draft
    url = f"{shopify_base()}/products.json?limit=250&fields=id,title,images,status&status=draft"
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
    return {"phase1_done": [], "phase2_done": []}

def save_progress(progress):
    with _file_lock:
        PROGRESS_FILE.write_text(json.dumps(progress, indent=2))

def log_deleted(filepath, pid, title, reason, image_url=""):
    with _file_lock:
        data = []
        if filepath.exists():
            data = json.loads(filepath.read_text())
        data.append({"id": pid, "title": title, "reason": reason, "image": image_url,
                      "time": time.strftime("%Y-%m-%dT%H:%M:%S")})
        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False))

def delete_product(pid, token):
    headers = shopify_headers(token)
    for _ in range(3):
        r = requests.delete(f"{shopify_base()}/products/{pid}.json", headers=headers, timeout=15)
        if r.status_code in (200, 204):
            return True
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 2)))
            continue
        break
    return False

def classify_image(image_url, api_key):
    """Vision classify: is this a photo of a physical resin model product? YES/NO."""
    try:
        # Download and resize
        dl = requests.get(image_url, timeout=15,
            headers={"User-Agent": "Mozilla/5.0"})
        if dl.status_code != 200 or len(dl.content) < 500:
            return "NO"
        from PIL import Image
        from io import BytesIO
        import base64
        img = Image.open(BytesIO(dl.content)).convert("RGB")
        img.thumbnail((512, 512))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=80)
        b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return "NO"

    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 10,
                  "messages": [{"role": "user", "content": [
                      {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                      {"type": "text", "text": "Is this image a photograph of a physical resin model, figure, or model kit product? Answer ONLY 'YES' or 'NO'. Answer NO if the image is: an emoji, cartoon, clipart, stock photo of unrelated content (smiley faces, random graphics, logos, text-only images, generic illustrations), or anything that is not a photograph of an actual resin/plastic model product. Answer YES only if it clearly shows a physical miniature, figure, bust, vehicle, or model kit."}
                  ]}]},
            timeout=30)
        if r.status_code == 200:
            answer = r.json()["content"][0]["text"].strip().upper()
            return "YES" if "YES" in answer else "NO"
    except Exception:
        pass
    return "YES"  # keep on error

def main():
    dry_run = "--dry-run" in sys.argv
    phase1_only = "--phase1" in sys.argv
    phase2_only = "--phase2" in sys.argv
    run_phase1 = not phase2_only
    run_phase2 = not phase1_only

    api_key = config.ANTHROPIC_API_KEY
    token = get_shopify_token()

    print(f"\n══════════════════════════════════════")
    print(f"  CastForge Image Cleanup")
    print(f"══════════════════════════════════════")
    print(f"  Dry run: {dry_run}\n")

    print("  Fetching all products...")
    products = fetch_all_products(token)
    print(f"  Found {len(products)} products\n")

    progress = load_progress()
    p1_done = set(progress["phase1_done"])
    p2_done = set(progress["phase2_done"])

    # ══ Phase 1: Delete 0-image products ══
    if run_phase1:
        zero_img = [p for p in products if len(p.get("images", [])) == 0 and p["id"] not in p1_done]
        print(f"  ── Phase 1: {len(zero_img)} products with 0 images ──\n")
        deleted = 0
        for i, p in enumerate(zero_img):
            if deleted >= SAFETY_LIMIT:
                print(f"\n  ⚠ SAFETY HALT: {deleted} deletions. Review {DELETED_0_FILE} and restart.")
                break
            pid, title = p["id"], p.get("title", "")[:60]
            if dry_run:
                print(f"  [{i+1}/{len(zero_img)}] 🗑 WOULD DELETE: {pid} — {title}")
            else:
                if delete_product(pid, token):
                    log_deleted(DELETED_0_FILE, pid, title, "0 images")
                    print(f"  [{i+1}/{len(zero_img)}] 🗑 DELETED: {pid} — {title}")
                    deleted += 1
                else:
                    print(f"  [{i+1}/{len(zero_img)}] ✗ DELETE FAILED: {pid}")
            progress["phase1_done"].append(pid)
            save_progress(progress)
            time.sleep(0.3)
        print(f"\n  Phase 1 done: {deleted} deleted\n")

    # ══ Phase 2: Vision classify first image ══
    if run_phase2:
        with_images = [p for p in products if len(p.get("images", [])) > 0 and p["id"] not in p2_done]
        print(f"  ── Phase 2: {len(with_images)} products to classify ──\n")
        deleted = [0]
        kept = [0]
        t0 = time.time()

        def process_one(item):
            i, p = item
            pid = p["id"]
            title = p.get("title", "")[:60]
            img_url = p["images"][0].get("src", "")

            if deleted[0] >= SAFETY_LIMIT:
                return

            verdict = classify_image(img_url, api_key)

            if verdict == "NO":
                if dry_run:
                    print(f"  [{i+1}/{len(with_images)}] ✗ WOULD DELETE: {title}")
                else:
                    if delete_product(pid, token):
                        with _file_lock:
                            deleted[0] += 1
                        log_deleted(DELETED_BAD_FILE, pid, title, "bad image (emoji/clipart/non-product)", img_url)
                        print(f"  [{i+1}/{len(with_images)}] ✗ DELETE: {title}")
                    else:
                        print(f"  [{i+1}/{len(with_images)}] ✗ DELETE FAILED: {title}")
            else:
                with _file_lock:
                    kept[0] += 1
                if (i + 1) % 50 == 0:
                    elapsed = time.time() - t0
                    rate = (i + 1) / max(elapsed, 1) * 60
                    print(f"  [{i+1}/{len(with_images)}] ✓ kept={kept[0]} deleted={deleted[0]} | {rate:.0f}/min")

            progress["phase2_done"].append(pid)
            save_progress(progress)

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(process_one, (i, p)) for i, p in enumerate(with_images)]
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    print(f"  Worker error: {e}")

        print(f"\n  Phase 2 done: {kept[0]} kept, {deleted[0]} deleted\n")

if __name__ == "__main__":
    main()
