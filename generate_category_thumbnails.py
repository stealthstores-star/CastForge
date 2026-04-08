#!/usr/bin/env python3
"""
Generate branded category thumbnails using Gemini 2.5 Flash Image.
Editorial hero images with burned-in category text overlay.

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
from PIL import Image, ImageDraw, ImageFont

import config
from uploader import get_shopify_token

OUTPUT_DIR = Path("category_thumbnails")

GLOBAL_PROMPT = """Ultra-premium editorial product photography for a luxury resin model store category banner. Cinematic dramatic lighting with deep shadows and orange/amber rim lighting. Dark moody atmosphere. Shallow depth of field. Museum-quality display aesthetic. Shot on Phase One medium format, 85mm lens, f/2.8. Photorealistic, hyperdetailed, 8k resolution. Square 1:1 composition. No text, no logos, no watermarks, no brand names visible. Professional hobby store catalog photography style inspired by Games Workshop Forge World and Weta Workshop.

"""

CATEGORIES = [
    ("wargaming-heroes-characters", "WARGAMING HEROES",
     "Three heroic fantasy warrior miniatures arranged in a dramatic triangular composition on a cracked stone plinth: a paladin in ornate gold armor with glowing sword, a hooded ranger drawing a bow, and a female mage with staff crackling with blue energy. Battle-worn, painted to competition level. Warm torch light from the side."),

    ("wargaming-infantry", "WARGAMING INFANTRY",
     "A squad of 1/35 scale WWII soldiers advancing through muddy trenches. Five figures in weathered uniforms with rifles and gear, dramatic ground-level perspective, morning mist, puddles reflecting sky, shallow depth of field focusing on the lead soldier's face. Overcast atmospheric lighting."),

    ("scale-military-vehicles", "MILITARY VEHICLES",
     "A 1/35 scale Tiger tank in desert camouflage parked dramatically on a diorama base with sand and debris, photographed from a low hero angle with golden hour sunlight streaming across the hull. Heat shimmer, dust motes in the light. Weathered with oil stains and battle damage."),

    ("scale-aircraft", "AIRCRAFT",
     "A meticulously detailed 1/48 scale P-51 Mustang fighter plane on a premium display stand, photographed three-quarter front from below to emphasize scale. Hangar bay environment with soft industrial lighting, another aircraft silhouetted in the background, tools scattered on workbench."),

    ("scale-ships-naval", "SHIPS & NAVAL",
     "A highly detailed 1/350 scale WWII battleship model on a glass ocean base, shot from water level, dramatic stormy sky in background with volumetric god rays breaking through clouds, foam and wake effects around the hull. Epic naval battle scene atmosphere."),

    ("busts-portraits", "BUSTS & PORTRAITS",
     "Three premium resin character busts displayed on dark wooden pedestals in a gallery setting: a grizzled Viking warrior, an elegant elven noblewoman, and a cyberpunk mercenary. Spotlight from above casting dramatic shadows, dust particles visible in the light beams, velvet backdrop."),

    ("fantasy-warriors", "FANTASY WARRIORS",
     "An epic fantasy battle scene with five painted fantasy miniatures mid-combat on a ruined castle ramparts diorama: an orc chieftain, dwarven berserker, elf archer, demon warrior, and knight. Magical fire effects, glowing runes, smoke, dramatic low angle shot."),

    ("scifi-figures", "SCI-FI FIGURES",
     "A cyberpunk marketplace diorama with three detailed sci-fi resin figures: a street samurai with katana, an armored bounty hunter with plasma rifle, and a hacker in neon hoodie. Neon blue and magenta lighting, rain-slicked streets, holographic signs in background blurred."),

    ("anime-characters", "ANIME CHARACTERS",
     "Three premium anime-style resin figures displayed in a collector's showcase: a magical girl in flowing dress with glowing wand, a samurai girl with sword, and a mech pilot in flight suit. Soft diffused studio lighting with cherry blossom petals falling, pastel gradient background."),

    ("terrain-buildings-ruins", "TERRAIN & BUILDINGS",
     "An elaborate 1/35 scale diorama of a ruined European village after WWII bombing: crumbling cathedral, cobblestone street, burning building, scattered debris, shell craters. Late afternoon golden light through smoke, cinematic wide shot, rich atmospheric haze."),

    ("scale-cars-motorcycles", "CARS & MOTORCYCLES",
     "A highly detailed 1/24 scale classic Ferrari in candy apple red on a polished showroom floor with chrome reflections. Professional automotive photography lighting with strip softboxes reflected in the paint, subtle smoke at ground level, premium dealership aesthetic."),

    ("accessories", "ACCESSORIES",
     "A beautifully curated flat lay of premium modeling tools and hobby supplies on a dark leather workbench: paint brushes in a glass jar, Citadel-style paint pots in rainbow arrangement, precision hobby knife, tweezers, magnifying lamp, clippers, and a half-finished miniature. Overhead dramatic lighting, shallow depth of field, craftsman workshop aesthetic."),
]


def generate_image(prompt, api_key):
    """Generate image via google-genai SDK. Returns raw bytes or None."""
    from google import genai
    client = genai.Client(api_key=api_key)

    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-image",
                contents=[prompt],
            )
            for part in response.candidates[0].content.parts:
                if part.inline_data is not None:
                    return part.inline_data.data
        except Exception as e:
            if attempt == 0:
                print(f"retry...", end=" ", flush=True)
                time.sleep(3)
            else:
                print(f"FAILED: {e}")
    return None


def get_font(size=70):
    """Try bold display fonts in order of preference."""
    font_paths = [
        # Anton (if downloaded)
        str(OUTPUT_DIR / "Anton-Regular.ttf"),
        # System fonts
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Impact.ttf",
        "/System/Library/Fonts/Supplemental/Impact.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for p in font_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    # Try downloading Anton from Google Fonts
    try:
        print("    (downloading Anton font...)", end=" ", flush=True)
        r = requests.get("https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf", timeout=10)
        if r.status_code == 200:
            font_path = OUTPUT_DIR / "Anton-Regular.ttf"
            font_path.write_bytes(r.content)
            return ImageFont.truetype(str(font_path), size)
    except Exception:
        pass
    return ImageFont.load_default()


def burn_text(img, text, font):
    """Add category name with gradient overlay on bottom 35%."""
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size

    # Gradient overlay on bottom 35%
    grad_start = int(h * 0.65)
    for y in range(grad_start, h):
        progress = (y - grad_start) / (h - grad_start)
        alpha = int(progress * 200)
        draw.rectangle([(0, y), (w, y + 1)], fill=(0, 0, 0, alpha))

    # Text position: bottom-left with padding
    draw_rgb = ImageDraw.Draw(img)
    bbox = draw_rgb.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = 40
    y = h - th - 50

    # Drop shadow
    for ox, oy in [(2, 2), (3, 3), (1, 1)]:
        draw_rgb.text((x + ox, y + oy), text, fill=(0, 0, 0), font=font)

    # White text
    draw_rgb.text((x, y), text, fill=(255, 255, 255), font=font)

    return img


def upload_as_collection_image(col_id, image_path, token):
    """Upload image as collection image."""
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"
    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")
    for endpoint in ["custom_collections", "smart_collections"]:
        key = endpoint.rstrip("s")
        r = requests.put(f"{base}/{endpoint}/{col_id}.json", headers=headers,
            json={key: {"id": col_id, "image": {"attachment": encoded}}}, timeout=60)
        if r.status_code in (200, 201):
            return True
    return False


def main():
    test_mode = "--test" in sys.argv
    no_upload = "--no-upload" in sys.argv

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("\n  ERROR: export GEMINI_API_KEY=your_key")
        print("  Get one at: https://aistudio.google.com/apikey\n")
        sys.exit(1)

    token = get_shopify_token() if not no_upload else None
    col_map = json.loads(Path("collection_map.json").read_text()) if Path("collection_map.json").exists() else {}
    OUTPUT_DIR.mkdir(exist_ok=True)

    cats = CATEGORIES[:1] if test_mode else CATEGORIES
    font = get_font(70)

    print(f"\n  Generating {len(cats)} editorial category thumbnails\n")

    for handle, label, scene in cats:
        col_id = col_map.get(handle)
        prompt = GLOBAL_PROMPT + scene

        print(f"  [{label}]")
        print(f"    Generating...", end=" ", flush=True)

        image_bytes = generate_image(prompt, api_key)
        if not image_bytes:
            continue

        # Process: resize + burn text
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img = img.resize((1200, 1200), Image.LANCZOS)
        img = burn_text(img, label, font)

        output_path = OUTPUT_DIR / f"category-{handle}.jpg"
        img.save(str(output_path), "JPEG", quality=92)
        print(f"saved → {output_path}")

        if not no_upload and col_id and token:
            print(f"    Uploading...", end=" ", flush=True)
            if upload_as_collection_image(col_id, output_path, token):
                print("✓ collection image set")
            else:
                print("✗ upload failed")
        elif not col_id:
            print(f"    No collection ID — local only")

        time.sleep(3)

    print(f"\n  Done! {OUTPUT_DIR}/\n")


if __name__ == "__main__":
    main()
