#!/usr/bin/env python3
"""
Generate category thumbnail composites — 2x2 grid of top products per collection.
Uploads to Shopify Files API and sets as collection image.

Usage: python3 generate_category_thumbnails.py
"""
import json, os, sys, time, io, requests
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

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

def get_font(size=42):
    """Try Anton, DejaVuSans-Bold, or fallback."""
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
    ]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()

def download_image(url, size=600):
    """Download and resize image to square."""
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200 or len(r.content) < 1000:
            return None
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        img = img.resize((size, size), Image.LANCZOS)
        return img
    except Exception:
        return None

def create_composite(images, title, output_path):
    """Create 2x2 grid with gradient overlay and title."""
    canvas = Image.new("RGB", (1200, 1200), (17, 17, 17))

    # Place images in 2x2 grid
    positions = [(0, 0), (600, 0), (0, 600), (600, 600)]
    for i, pos in enumerate(positions):
        if i < len(images) and images[i]:
            canvas.paste(images[i], pos)

    # Dark gradient overlay on bottom 40%
    draw = ImageDraw.Draw(canvas)
    for y in range(720, 1200):
        alpha = int((y - 720) / 480 * 200)
        draw.rectangle([(0, y), (1200, y + 1)], fill=(0, 0, 0, alpha) if alpha < 200 else (0, 0, 0))

    # Redraw with full overlay
    overlay = Image.new("RGBA", (1200, 1200), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)
    for y in range(720, 1200):
        a = min(int((y - 720) / 480 * 220), 220)
        draw_ov.rectangle([(0, y), (1200, y + 1)], fill=(0, 0, 0, a))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")

    # Title text
    draw = ImageDraw.Draw(canvas)
    font = get_font(48)
    draw.text((40, 1100), title.upper(), fill=(255, 255, 255), font=font)

    # Save
    canvas.save(str(output_path), "JPEG", quality=92)
    return output_path

def upload_to_shopify_files(filepath, token):
    """Upload image to Shopify Files via staged upload."""
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    # Create staged upload
    r = requests.post(f"{base}/graphql.json", headers=headers, json={
        "query": """mutation { stagedUploadsCreate(input: [{
            resource: FILE, filename: "%s", mimeType: "image/jpeg",
            httpMethod: POST
        }]) { stagedTargets { url parameters { name value } resourceUrl } userErrors { message } } }""" % filepath.name
    }, timeout=30)

    if r.status_code != 200:
        print(f"    Staged upload failed: {r.status_code}")
        return None

    data = r.json().get("data", {}).get("stagedUploadsCreate", {})
    targets = data.get("stagedTargets", [])
    if not targets:
        print(f"    No staged targets returned")
        return None

    target = targets[0]
    upload_url = target["url"]
    params = {p["name"]: p["value"] for p in target["parameters"]}
    resource_url = target["resourceUrl"]

    # Upload file
    with open(filepath, "rb") as f:
        files = {"file": (filepath.name, f, "image/jpeg")}
        ur = requests.post(upload_url, data=params, files=files, timeout=60)
        if ur.status_code not in (200, 201, 204):
            print(f"    File upload failed: {ur.status_code}")
            return None

    return resource_url

def set_collection_image(collection_id, image_url, token):
    """Set collection image via REST API."""
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"
    r = requests.put(f"{base}/custom_collections/{collection_id}.json", headers=headers,
        json={"custom_collection": {"id": collection_id, "image": {"src": image_url}}}, timeout=15)
    # Also try smart collection
    if r.status_code not in (200, 201):
        r = requests.put(f"{base}/smart_collections/{collection_id}.json", headers=headers,
            json={"smart_collection": {"id": collection_id, "image": {"src": image_url}}}, timeout=15)
    return r.status_code in (200, 201)

def main():
    token = get_shopify_token()
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Load collection map for IDs
    col_map = json.loads(Path("collection_map.json").read_text()) if Path("collection_map.json").exists() else {}

    print(f"\n  Generating category thumbnails for {len(CATEGORIES)} collections\n")

    for handle, title in CATEGORIES:
        print(f"  {title}...", end=" ", flush=True)
        col_id = col_map.get(handle)

        # Fetch top 4 products from collection
        r = requests.get(f"{base}/collections/{col_id}/products.json?limit=4&fields=id,images",
            headers=headers, timeout=15) if col_id else None
        products = r.json().get("products", []) if r and r.status_code == 200 else []

        # Download product images
        images = []
        for p in products[:4]:
            imgs = p.get("images", [])
            if imgs:
                img = download_image(imgs[0].get("src", ""))
                if img:
                    images.append(img)

        if not images:
            print("no images found, skipping")
            continue

        # Pad to 4 if needed
        while len(images) < 4:
            images.append(images[0])

        # Create composite
        output_path = OUTPUT_DIR / f"category-{handle}.jpg"
        create_composite(images, title, output_path)
        print(f"saved → ", end="", flush=True)

        # Upload and set as collection image
        if col_id:
            uploaded_url = upload_to_shopify_files(output_path, token)
            if uploaded_url:
                if set_collection_image(col_id, uploaded_url, token):
                    print(f"✓ set as collection image")
                else:
                    print(f"uploaded but failed to set")
            else:
                print(f"upload failed (use local file)")
        else:
            print(f"no collection ID, saved locally only")

        time.sleep(1)

    print(f"\n  Done! Thumbnails in {OUTPUT_DIR}/\n")

if __name__ == "__main__":
    main()
