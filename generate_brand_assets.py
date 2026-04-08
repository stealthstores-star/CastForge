#!/usr/bin/env python3
"""
Generate brand assets via Gemini and upload to Shopify.

1. Favicon: 512x512 orange "C" on black → resize to 32/180/192
2. OG image: 1200x630 social share with logo + tagline
3. Hero banner: 2400x1200 atmospheric background

Uploads to Shopify Files API and saves URLs.

Usage: python3 generate_brand_assets.py
"""
import base64, io, json, os, time
import requests
from PIL import Image, ImageDraw, ImageFont
import config
from uploader import get_shopify_token

OUTPUT_DIR = "brand_assets"


def generate_favicon():
    """Generate a 512x512 favicon: orange C on dark background."""
    img = Image.new("RGBA", (512, 512), (10, 10, 10, 255))
    draw = ImageDraw.Draw(img)

    # Try to load a bold font, fall back to default
    font_size = 380
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except (OSError, IOError):
            font = ImageFont.load_default()

    # Draw the C
    color = (255, 107, 26)  # CastForge orange
    bbox = draw.textbbox((0, 0), "C", font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (512 - w) // 2 - bbox[0]
    y = (512 - h) // 2 - bbox[1]
    draw.text((x, y), "C", fill=color, font=font)

    # Save at multiple sizes
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    sizes = {"favicon-512.png": 512, "favicon-192.png": 192, "favicon-180.png": 180, "favicon-32.png": 32}
    paths = {}
    for filename, size in sizes.items():
        resized = img.resize((size, size), Image.LANCZOS)
        path = os.path.join(OUTPUT_DIR, filename)
        resized.save(path, "PNG")
        paths[filename] = path
        print(f"    {filename} ({size}x{size})")
    return paths


def generate_og_image():
    """Generate a 1200x630 OG image with branding."""
    img = Image.new("RGB", (1200, 630), (10, 10, 10))
    draw = ImageDraw.Draw(img)

    # Gradient background
    for y in range(630):
        r = int(10 + (20 * y / 630))
        g = int(10 + (8 * y / 630))
        b = int(10 + (2 * y / 630))
        draw.line([(0, y), (1200, y)], fill=(r, g, b))

    # Accent line at top
    draw.rectangle([(0, 0), (1200, 4)], fill=(255, 107, 26))

    # Logo text
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
    except (OSError, IOError):
        title_font = ImageFont.load_default()
    try:
        sub_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except (OSError, IOError):
        sub_font = ImageFont.load_default()

    draw.text((80, 230), "CASTFORGE", fill=(255, 107, 26), font=title_font)
    draw.text((80, 320), "Premium Resin Models Since 2024", fill=(180, 180, 180), font=sub_font)

    # Bottom accent
    draw.rectangle([(0, 626), (1200, 630)], fill=(255, 107, 26))

    path = os.path.join(OUTPUT_DIR, "og-image.jpg")
    img.save(path, "JPEG", quality=90)
    print(f"    og-image.jpg (1200x630)")
    return path


def generate_hero_banner():
    """Generate a 2400x1200 hero background with dramatic gradient."""
    img = Image.new("RGB", (2400, 1200), (10, 10, 10))
    draw = ImageDraw.Draw(img)

    # Create atmospheric gradient with warm tones
    for y in range(1200):
        for x in range(0, 2400, 4):
            # Warm glow from right side
            dist_x = x / 2400.0
            dist_y = y / 1200.0
            r = int(10 + 30 * dist_x * (1 - abs(dist_y - 0.5) * 2))
            g = int(10 + 12 * dist_x * (1 - abs(dist_y - 0.5) * 2))
            b = int(10 + 4 * dist_x)
            draw.rectangle([(x, y), (x + 3, y)], fill=(min(r, 40), min(g, 22), min(b, 14)))

    # Subtle light source (warm spotlight from right)
    import math
    cx, cy = 1900, 500
    for angle in range(360):
        for radius in range(10, 600, 2):
            x = int(cx + radius * math.cos(math.radians(angle)))
            y = int(cy + radius * math.sin(math.radians(angle)))
            if 0 <= x < 2400 and 0 <= y < 1200:
                intensity = max(0, 1 - radius / 600)
                r = int(40 * intensity)
                g = int(16 * intensity)
                b = int(6 * intensity)
                px = img.getpixel((x, y))
                img.putpixel((x, y), (min(px[0] + r, 60), min(px[1] + g, 30), min(px[2] + b, 18)))

    path = os.path.join(OUTPUT_DIR, "hero-bg.jpg")
    img.save(path, "JPEG", quality=85)
    print(f"    hero-bg.jpg (2400x1200)")
    return path


def try_gemini_hero():
    """Attempt to generate hero via Gemini with retry. Falls back to PIL if unavailable."""
    try:
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            print("  No Gemini API key found, using PIL fallback for hero")
            return None

        client = genai.Client(api_key=api_key)
        prompt = ("Atmospheric hero banner for premium resin model store, "
                  "painted miniatures arranged on dark wooden table, "
                  "dramatic side lighting, shallow depth of field, cinematic, "
                  "dark background, warm amber highlights, no text, 2400x1200")

        for attempt in range(5):
            try:
                print(f"    Gemini attempt {attempt + 1}/5...", end=" ", flush=True)
                response = client.models.generate_content(
                    model="gemini-2.5-flash-image",
                    contents=prompt
                )
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'inline_data') and part.inline_data:
                        img_data = base64.b64decode(part.inline_data.data)
                        img = Image.open(io.BytesIO(img_data))
                        img = img.resize((2400, 1200), Image.LANCZOS)
                        path = os.path.join(OUTPUT_DIR, "hero-bg.jpg")
                        img.save(path, "JPEG", quality=90)
                        print(f"success!")
                        return path
                print("no image in response")
            except Exception as e:
                print(f"failed ({e})")
                if attempt < 4:
                    wait = 30 * (attempt + 1)
                    print(f"    Retrying in {wait}s...")
                    time.sleep(wait)
    except ImportError:
        print("  google.genai not installed, using PIL fallback")
    except Exception as e:
        print(f"  Gemini hero generation failed: {e}")
    return None


def upload_to_shopify(token, filepath, filename):
    """Upload file to Shopify via staged upload + file create."""
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    gql = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}/graphql.json"

    # Get file size and MIME type
    file_size = os.path.getsize(filepath)
    mime = "image/png" if filepath.endswith(".png") else "image/jpeg"

    # Stage upload
    stage_query = """
    mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
      stagedUploadsCreate(input: $input) {
        stagedTargets {
          url
          resourceUrl
          parameters { name value }
        }
        userErrors { field message }
      }
    }
    """
    stage_vars = {
        "input": [{
            "filename": filename,
            "mimeType": mime,
            "resource": "FILE",
            "fileSize": str(file_size),
            "httpMethod": "POST"
        }]
    }
    r = requests.post(gql, headers=headers, json={"query": stage_query, "variables": stage_vars}, timeout=30)
    if r.status_code != 200:
        print(f"    Stage upload failed: {r.status_code}")
        return None

    data = r.json().get("data", {}).get("stagedUploadsCreate", {})
    if data.get("userErrors"):
        print(f"    Stage errors: {data['userErrors']}")
        return None

    target = data["stagedTargets"][0]
    upload_url = target["url"]
    resource_url = target["resourceUrl"]

    # Upload to staged URL
    form_data = {p["name"]: p["value"] for p in target["parameters"]}
    with open(filepath, "rb") as f:
        files = {"file": (filename, f, mime)}
        r = requests.post(upload_url, data=form_data, files=files, timeout=60)
    if r.status_code not in (200, 201, 204):
        print(f"    File upload failed: {r.status_code}")
        return None

    # Create file in Shopify
    create_query = """
    mutation fileCreate($files: [FileCreateInput!]!) {
      fileCreate(files: $files) {
        files { id alt }
        userErrors { field message }
      }
    }
    """
    create_vars = {
        "files": [{
            "alt": filename.replace("-", " ").replace(".jpg", "").replace(".png", ""),
            "contentType": "IMAGE",
            "originalSource": resource_url
        }]
    }
    r = requests.post(gql, headers=headers, json={"query": create_query, "variables": create_vars}, timeout=30)
    if r.status_code == 200:
        fdata = r.json().get("data", {}).get("fileCreate", {})
        if fdata.get("files"):
            print(f"    Uploaded to Shopify: {filename}")
            return resource_url

    return None


def upload_theme_asset(token, filepath, key):
    """Upload file as a theme asset (for hero-bg.jpg)."""
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}

    # Get active theme
    r = requests.get(f"{base}/themes.json", headers=headers, timeout=15)
    if r.status_code != 200:
        print(f"    Could not fetch themes: {r.status_code}")
        return None

    themes = r.json().get("themes", [])
    main_theme = next((t for t in themes if t["role"] == "main"), None)
    if not main_theme:
        print("    No main theme found")
        return None

    tid = main_theme["id"]
    with open(filepath, "rb") as f:
        data = base64.b64encode(f.read()).decode()

    r = requests.put(
        f"{base}/themes/{tid}/assets.json",
        headers=headers,
        json={"asset": {"key": f"assets/{key}", "attachment": data}},
        timeout=60
    )
    if r.status_code == 200:
        url = r.json().get("asset", {}).get("public_url", "")
        print(f"    Uploaded theme asset: assets/{key}")
        return url
    else:
        print(f"    Theme asset upload failed: {r.status_code} {r.text[:200]}")
        return None


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    token = get_shopify_token()

    print("\n  Generating brand assets\n")

    # 1. Favicon
    print("  Favicon:")
    favicon_paths = generate_favicon()

    # 2. OG Image
    print("\n  OG Image:")
    og_path = generate_og_image()

    # 3. Hero Banner — try Gemini first, fall back to PIL
    print("\n  Hero Banner:")
    hero_path = try_gemini_hero()
    if not hero_path:
        hero_path = generate_hero_banner()

    # Upload
    print("\n  Uploading to Shopify...\n")

    # Upload favicon to Shopify Files
    for fname, fpath in favicon_paths.items():
        upload_to_shopify(token, fpath, fname)
        time.sleep(1)

    # Upload OG image to Shopify Files
    upload_to_shopify(token, og_path, "og-image.jpg")
    time.sleep(1)

    # Upload hero as theme asset (so home-hero.liquid can reference it)
    upload_theme_asset(token, hero_path, "hero-bg.jpg")

    print("\n  Done! Assets generated and uploaded.")
    print(f"  Local copies saved to {OUTPUT_DIR}/")
    print("  Update theme settings with favicon URLs from Shopify Files.\n")


if __name__ == "__main__":
    main()
