#!/usr/bin/env python3
"""
Generate category thumbnails — pick the SINGLE best product image per collection
using Haiku vision scoring. Upload as collection image.

Usage: python3 generate_category_thumbnails.py
       python3 generate_category_thumbnails.py --dry-run   # Score but don't upload
"""
import json, os, sys, time, io, base64, requests
from pathlib import Path
from PIL import Image

import config
from uploader import get_shopify_token

CATEGORIES = [
    ("wargaming-heroes-characters", "Wargaming Heroes"),
    ("wargaming-infantry", "Wargaming Infantry"),
    ("scale-military-vehicles", "Military Vehicles"),
    ("scale-aircraft", "Aircraft"),
    ("scale-ships-naval", "Ships & Naval"),
    ("busts-portraits", "Busts & Portraits"),
    ("fantasy-warriors", "Fantasy Warriors"),
    ("scifi-figures", "Sci-Fi Figures"),
    ("anime-characters", "Anime Characters"),
    ("terrain-buildings-ruins", "Terrain & Buildings"),
    ("scale-cars-motorcycles", "Cars & Motorcycles"),
    ("accessories", "Accessories"),
]

OUTPUT_DIR = Path("category_thumbnails")

SCORE_PROMPT = "Rate this image 1-10 on how visually striking and clean it is for a premium hobby store category thumbnail. Criteria: professional lighting, no watermarks, no Chinese text overlays, clear subject, dark or neutral background. Respond with only a number 1-10."

def download_and_resize(url, size=512):
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200 or len(r.content) < 2000:
            return None, None
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        img.thumbnail((size, size))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
        return img, b64
    except Exception:
        return None, None

def score_image(b64, api_key):
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 10,
                  "messages": [{"role": "user", "content": [
                      {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                      {"type": "text", "text": SCORE_PROMPT}
                  ]}]}, timeout=30)
        if r.status_code == 200:
            text = r.json()["content"][0]["text"].strip()
            import re
            m = re.search(r"(\d+)", text)
            return int(m.group(1)) if m else 0
    except Exception:
        pass
    return 0

def crop_square_with_gradient(img):
    """Crop to 1:1 center, add dark gradient on bottom."""
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    img = img.resize((1200, 1200), Image.LANCZOS)

    # Add gradient overlay on bottom 40%
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img, "RGBA")
    for y in range(720, 1200):
        alpha = int((y - 720) / 480 * 180)
        draw.rectangle([(0, y), (1200, y + 1)], fill=(0, 0, 0, min(alpha, 180)))

    return img

def set_collection_image(col_id, image_path, token):
    """Upload image as collection image via base64."""
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")

    # Try custom collection
    r = requests.put(f"{base}/custom_collections/{col_id}.json", headers=headers,
        json={"custom_collection": {"id": col_id, "image": {"attachment": encoded}}}, timeout=60)
    if r.status_code in (200, 201):
        return True
    # Try smart collection
    r = requests.put(f"{base}/smart_collections/{col_id}.json", headers=headers,
        json={"smart_collection": {"id": col_id, "image": {"attachment": encoded}}}, timeout=60)
    return r.status_code in (200, 201)

def main():
    dry_run = "--dry-run" in sys.argv
    api_key = config.ANTHROPIC_API_KEY
    token = get_shopify_token()
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"
    col_map = json.loads(Path("collection_map.json").read_text()) if Path("collection_map.json").exists() else {}
    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"\n  Generating category thumbnails ({len(CATEGORIES)} collections)")
    print(f"  Method: Haiku vision scoring, pick best single image\n")

    for handle, title in CATEGORIES:
        col_id = col_map.get(handle)
        if not col_id:
            print(f"  {title}: no collection ID, skipping")
            continue

        print(f"  {title}...", flush=True)

        # Fetch top 20 products
        r = requests.get(f"{base}/collections/{col_id}/products.json?limit=20&fields=id,title,images",
            headers=headers, timeout=15)
        products = r.json().get("products", []) if r.status_code == 200 else []

        if not products:
            print(f"    0 products, skipping")
            continue

        # Score each product's first image
        best_score, best_img, best_title = 0, None, ""
        candidates = 0
        for p in products:
            imgs = p.get("images", [])
            if not imgs:
                continue
            src = imgs[0].get("src", "")
            if not src:
                continue

            img, b64 = download_and_resize(src)
            if not b64:
                continue

            candidates += 1
            score = score_image(b64, api_key)
            ptitle = p.get("title", "")[:40]
            print(f"    {score}/10 — {ptitle}")

            if score > best_score:
                best_score = score
                best_img = img
                best_title = ptitle

            time.sleep(0.3)
            if candidates >= 10:  # Cap at 10 evaluations per collection
                break

        if not best_img:
            print(f"    No usable images found")
            continue

        # Crop to square with gradient
        final = crop_square_with_gradient(best_img)
        output_path = OUTPUT_DIR / f"category-{handle}.jpg"
        final.save(str(output_path), "JPEG", quality=92)
        print(f"    Winner: {best_score}/10 — {best_title}")

        if not dry_run and col_id:
            if set_collection_image(col_id, output_path, token):
                print(f"    ✓ Uploaded as collection image")
            else:
                print(f"    ✗ Upload failed")

        time.sleep(0.5)

    print(f"\n  Done! Thumbnails in {OUTPUT_DIR}/\n")

if __name__ == "__main__":
    main()
