#!/usr/bin/env python3
"""
Generate branded category thumbnails using Gemini 2.5 Flash Image (Nano Banana).

Setup:
    pip3 install google-genai Pillow
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


def generate_image(prompt, api_key):
    """Generate image using google-genai SDK with gemini-2.5-flash-image-preview."""
    from google import genai

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash-image",
        contents=[prompt],
    )

    for part in response.candidates[0].content.parts:
        if part.inline_data is not None:
            return part.inline_data.data  # raw image bytes

    print(f"    No image in response")
    return None


def process_and_save(image_bytes, output_path):
    """Resize to 1200x1200, save as JPEG."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img = img.resize((1200, 1200), Image.LANCZOS)
    img.save(str(output_path), "JPEG", quality=92)
    return output_path


def upload_as_collection_image(col_id, image_path, token):
    """Upload image as collection image via base64 attachment."""
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")

    for endpoint in ["custom_collections", "smart_collections"]:
        r = requests.put(f"{base}/{endpoint}/{col_id}.json", headers=headers,
            json={endpoint.rstrip("s"): {"id": col_id, "image": {"attachment": encoded}}}, timeout=60)
        if r.status_code in (200, 201):
            return True
    return False


def main():
    test_mode = "--test" in sys.argv
    no_upload = "--no-upload" in sys.argv

    api_key = os.environ.get("GEMINI_API_KEY", "")
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

    print(f"\n  Generating {len(categories)} thumbnails via Gemini 2.5 Flash Image\n")

    for handle, info in categories:
        name = info["name"]
        prompt = BASE_PROMPT.format(name=name, detail=info["detail"])
        col_id = col_map.get(handle)

        print(f"  [{name}]")
        print(f"    Generating...", end=" ", flush=True)

        try:
            image_bytes = generate_image(prompt, api_key)
        except Exception as e:
            print(f"FAILED: {e}")
            continue

        if not image_bytes:
            print("FAILED — no image returned")
            continue

        output_path = OUTPUT_DIR / f"category-{handle}.jpg"
        process_and_save(image_bytes, output_path)
        print(f"saved → {output_path}")

        if not no_upload and col_id and token:
            print(f"    Uploading...", end=" ", flush=True)
            if upload_as_collection_image(col_id, output_path, token):
                print("✓ set as collection image")
            else:
                print("✗ upload failed")
        elif not col_id:
            print(f"    No collection ID — saved locally only")

        time.sleep(2)

    print(f"\n  Done! Thumbnails in {OUTPUT_DIR}/\n")


if __name__ == "__main__":
    main()
