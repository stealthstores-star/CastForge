#!/usr/bin/env python3
"""
Generate branded category thumbnails using Gemini 2.5 Flash image generation.
Creates premium dark-themed hero images for each collection.

Setup:
    pip install google-generativeai Pillow
    export GEMINI_API_KEY=your_key_here

Usage:
    python3 generate_category_thumbnails.py --test          # Generate 1 category
    python3 generate_category_thumbnails.py                 # Generate all 12
    python3 generate_category_thumbnails.py --no-upload     # Generate without uploading
"""
import base64, io, json, os, sys, time
from pathlib import Path

import requests
from PIL import Image

import config
from uploader import get_shopify_token

OUTPUT_DIR = Path("category_thumbnails")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

CATEGORIES = {
    "wargaming-heroes-characters": {
        "name": "Wargaming Heroes",
        "detail": "a detailed 28mm fantasy warrior miniature centered, ornate armor and weapon visible, heroic pose"
    },
    "wargaming-infantry": {
        "name": "Wargaming Infantry",
        "detail": "a WWII soldier resin figure in dynamic combat pose, detailed uniform and equipment"
    },
    "scale-military-vehicles": {
        "name": "Military Vehicles",
        "detail": "a detailed 1/35 scale tank model on display, visible track links and turret detail"
    },
    "scale-aircraft": {
        "name": "Aircraft",
        "detail": "a 1/48 scale fighter jet model on a display stand, detailed cockpit and panel lines"
    },
    "scale-ships-naval": {
        "name": "Ships & Naval",
        "detail": "a 1/700 scale battleship model with detailed rigging and gun turrets"
    },
    "busts-portraits": {
        "name": "Busts & Portraits",
        "detail": "a premium resin character bust on a black pedestal, detailed facial features and shoulders"
    },
    "fantasy-warriors": {
        "name": "Fantasy Warriors",
        "detail": "a detailed fantasy warrior miniature with dramatic pose, sword and shield, flowing cloak"
    },
    "scifi-figures": {
        "name": "Sci-Fi Figures",
        "detail": "a futuristic sci-fi soldier resin figure, cyberpunk aesthetic, glowing elements"
    },
    "anime-characters": {
        "name": "Anime Characters",
        "detail": "a stylized anime character resin figure, dynamic action pose, detailed base"
    },
    "terrain-buildings-ruins": {
        "name": "Terrain & Buildings",
        "detail": "a detailed diorama terrain piece, ruined gothic building with rubble and debris"
    },
    "scale-cars-motorcycles": {
        "name": "Cars & Motorcycles",
        "detail": "a 1/24 scale sports car resin model on display, glossy paint finish, detailed interior"
    },
    "accessories": {
        "name": "Accessories",
        "detail": "a collection of hobby paints, brushes and modeling tools arranged professionally on dark surface"
    },
}

BASE_PROMPT = """Premium dark atmospheric product photography hero image for '{name}' category of a high-end resin model store. Moody studio lighting, dark background with subtle orange rim light, professional product showcase style. {detail}. Cinematic, 8k quality, dramatic shadows, no text, no watermarks, no logos. Square 1:1 format."""


def generate_with_gemini(prompt, api_key):
    """Generate image using Gemini 2.5 Flash via REST API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={api_key}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
        }
    }

    r = requests.post(url, json=payload, timeout=120)
    if r.status_code != 200:
        print(f"    API error {r.status_code}: {r.text[:200]}")
        return None

    data = r.json()
    candidates = data.get("candidates", [])
    if not candidates:
        print(f"    No candidates in response")
        return None

    for part in candidates[0].get("content", {}).get("parts", []):
        if "inlineData" in part:
            img_data = part["inlineData"]
            img_bytes = base64.b64decode(img_data["data"])
            return Image.open(io.BytesIO(img_bytes))

    print(f"    No image in response parts")
    return None


def generate_with_gemini_sdk(prompt, api_key):
    """Generate image using google-generativeai SDK."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.ImageGenerationModel("imagen-3.0-generate-002")
        result = model.generate_images(
            prompt=prompt,
            number_of_images=1,
            aspect_ratio="1:1",
        )
        if result.images:
            return result.images[0]._pil_image
    except ImportError:
        print("    google-generativeai not installed, using REST API")
    except Exception as e:
        print(f"    SDK error: {e}")
    return None


def process_image(img):
    """Resize to 1200x1200 and ensure JPEG."""
    img = img.convert("RGB")
    img = img.resize((1200, 1200), Image.LANCZOS)
    return img


def upload_as_collection_image(col_id, image_path, token):
    """Upload image as collection image via base64 attachment."""
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")

    # Try custom collection first
    r = requests.put(f"{base}/custom_collections/{col_id}.json", headers=headers,
        json={"custom_collection": {"id": col_id, "image": {"attachment": encoded}}}, timeout=60)
    if r.status_code in (200, 201):
        return True
    # Try smart collection
    r = requests.put(f"{base}/smart_collections/{col_id}.json", headers=headers,
        json={"smart_collection": {"id": col_id, "image": {"attachment": encoded}}}, timeout=60)
    return r.status_code in (200, 201)


def main():
    test_mode = "--test" in sys.argv
    no_upload = "--no-upload" in sys.argv

    api_key = GEMINI_API_KEY
    if not api_key:
        print("\n  ERROR: Set GEMINI_API_KEY environment variable")
        print("  Get one at: https://aistudio.google.com/apikey\n")
        sys.exit(1)

    token = get_shopify_token() if not no_upload else None
    col_map = json.loads(Path("collection_map.json").read_text()) if Path("collection_map.json").exists() else {}
    OUTPUT_DIR.mkdir(exist_ok=True)

    categories = list(CATEGORIES.items())
    if test_mode:
        categories = categories[:1]

    print(f"\n  Generating {len(categories)} category thumbnails via Gemini\n")

    for handle, info in categories:
        name = info["name"]
        detail = info["detail"]
        prompt = BASE_PROMPT.format(name=name, detail=detail)
        col_id = col_map.get(handle)

        print(f"  [{name}]")
        print(f"    Generating...", end=" ", flush=True)

        # Try SDK first, fall back to REST
        img = generate_with_gemini_sdk(prompt, api_key)
        if not img:
            img = generate_with_gemini(prompt, api_key)

        if not img:
            print("FAILED — no image generated")
            continue

        # Process and save
        img = process_image(img)
        output_path = OUTPUT_DIR / f"category-{handle}.jpg"
        img.save(str(output_path), "JPEG", quality=92)
        print(f"saved → {output_path}")

        # Upload
        if not no_upload and col_id and token:
            print(f"    Uploading to Shopify...", end=" ", flush=True)
            if upload_as_collection_image(col_id, output_path, token):
                print("✓ set as collection image")
            else:
                print("✗ upload failed (check collection type)")
        elif not col_id:
            print(f"    No collection ID for {handle} — saved locally only")

        time.sleep(2)  # Rate limit between generations

    print(f"\n  Done! Thumbnails in {OUTPUT_DIR}/")
    if test_mode:
        print(f"  Test mode — only generated 1. Run without --test for all 12.\n")
    else:
        print()


if __name__ == "__main__":
    main()
