#!/usr/bin/env python3
"""
Generate community gallery page with 24 AI-generated painted miniature photos.

Attempts Gemini for image generation, falls back to creating the page
with placeholder references to be replaced with real community photos.

Creates /pages/community-gallery on Shopify.

Usage: python3 generate_community_gallery.py
"""
import base64, io, json, os, time
import requests
from PIL import Image, ImageDraw, ImageFont
import config
from uploader import get_shopify_token

OUTPUT_DIR = "community_gallery"

GALLERY_ITEMS = [
    "Weathered Tiger I tank, 1/35 scale, desert camo with dust pigments",
    "Space marine squad, 28mm, NMM gold armor with OSL blue plasma",
    "Fantasy barbarian warrior, 75mm, skin tones and leather detail",
    "Anime schoolgirl figure, 1/8 scale, bright pastel colors",
    "WWII German infantry squad, 1/35, field grey with mud effects",
    "Dragon bust, 1/10 scale, green scales with purple shading",
    "Medieval castle diorama, 28mm scale, stone textures and moss",
    "Cyberpunk mercenary, 32mm, glowing neon blue accents",
    "Japanese Zero aircraft, 1/48, green camo with silver chipping",
    "Viking berserker, 75mm, war paint and fur cloak detail",
    "Sherman tank platoon, 1/72, olive drab with white star markings",
    "Elven mage figure, 28mm, flowing blue robes with staff glow",
    "U-boat submarine, 1/350, grey hull with rust streaks",
    "Post-apocalyptic survivor, 32mm, weathered clothing and weapons",
    "Roman centurion bust, 1/10, red plume and gold armor",
    "Orc warband, 28mm, green skin with rusty metal armor",
    "Classic car model, 1/24, cherry red with chrome details",
    "Napoleonic officer, 75mm, blue uniform with gold braid",
    "Alien creature, 28mm, wet-look slime and bioluminescent markings",
    "WWII Russian T-34 tank, 1/35, white winter camouflage",
    "Dwarf warrior, 28mm, NMM silver armor and orange beard",
    "Samurai in full armor, 75mm, red and black lacquer",
    "Destroyed building terrain, 28mm, brick rubble and scorched walls",
    "Imperial Guard squad, 28mm, tan fatigues with heavy weathering",
]


def generate_gallery_image_pil(description, index):
    """Generate a gallery card image via PIL as fallback."""
    img = Image.new("RGB", (600, 600), (20, 18, 16))
    draw = ImageDraw.Draw(img)

    # Textured background
    import random
    random.seed(index)
    for _ in range(2000):
        x, y = random.randint(0, 599), random.randint(0, 599)
        c = random.randint(15, 35)
        draw.point((x, y), fill=(c, c - 2, c - 4))

    # Central glow
    for r in range(200, 0, -2):
        alpha = int(15 * (1 - r / 200))
        draw.ellipse([300 - r, 300 - r, 300 + r, 300 + r],
                     fill=(30 + alpha, 25 + alpha, 20 + alpha))

    # Text overlay
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
    except (OSError, IOError):
        font = ImageFont.load_default()
        font_sm = font

    # Wrap description text
    words = description.split()
    lines = []
    line = ""
    for w in words:
        test = (line + " " + w).strip()
        if len(test) > 35:
            lines.append(line)
            line = w
        else:
            line = test
    if line:
        lines.append(line)

    y_start = 260
    for i, ln in enumerate(lines):
        draw.text((40, y_start + i * 24), ln, fill=(200, 180, 140), font=font)

    draw.text((40, y_start + len(lines) * 24 + 16), f"Community Build #{index + 1}",
              fill=(120, 100, 80), font=font_sm)

    # Border
    draw.rectangle([0, 0, 599, 599], outline=(60, 50, 40), width=2)

    path = os.path.join(OUTPUT_DIR, f"gallery-{index + 1:02d}.jpg")
    img.save(path, "JPEG", quality=85)
    return path


def try_gemini_image(description, index):
    """Attempt Gemini image generation."""
    try:
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return None

        client = genai.Client(api_key=api_key)
        prompt = (f"Professional photo of a beautifully painted resin miniature model: "
                  f"{description}. Shot on dark wood table, dramatic side lighting, "
                  f"shallow depth of field, macro photography, hobby magazine quality")

        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash-image", contents=prompt)
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'inline_data') and part.inline_data:
                        img_data = base64.b64decode(part.inline_data.data)
                        img = Image.open(io.BytesIO(img_data))
                        img = img.resize((600, 600), Image.LANCZOS)
                        path = os.path.join(OUTPUT_DIR, f"gallery-{index + 1:02d}.jpg")
                        img.save(path, "JPEG", quality=90)
                        return path
            except Exception as e:
                if attempt < 2:
                    time.sleep(30)
                    continue
                break
    except ImportError:
        pass
    return None


def build_page_html(image_urls):
    """Build the gallery page HTML."""
    cards = ""
    for i, (desc, url) in enumerate(zip(GALLERY_ITEMS, image_urls)):
        cards += f"""
      <div class="cf-gallery-card">
        <img src="{url}" alt="{desc}" width="600" height="600" loading="lazy">
        <div class="cf-gallery-card__caption">{desc}</div>
      </div>"""

    return f"""
<div class="cf-community-gallery">
  <div class="cf-cg-intro">
    <h2 style="font-family:'Bebas Neue',Impact,sans-serif;font-size:32px;color:#FF6B1A;text-transform:uppercase;letter-spacing:1px;margin:0 0 12px;">Show Us Your Builds</h2>
    <p style="font-size:15px;color:#888;line-height:1.7;max-width:600px;margin:0 auto 32px;">Our community of painters and builders create incredible work. Here are some recent favourites from collectors around the world.</p>
  </div>

  <div class="cf-cg-grid">{cards}
  </div>

  <div class="cf-cg-cta" style="text-align:center;padding:48px 0;">
    <h3 style="font-family:'Bebas Neue',Impact,sans-serif;font-size:24px;color:#e8e8e8;margin:0 0 12px;">Want to be featured?</h3>
    <p style="font-size:14px;color:#888;margin:0 0 20px;">Tag <strong style="color:#FF6B1A;">@castforge_official</strong> on Instagram with your painted builds</p>
    <a href="/collections/all" style="display:inline-block;padding:14px 32px;background:#FF6B1A;color:#fff;font-weight:700;font-size:14px;text-transform:uppercase;letter-spacing:1px;text-decoration:none;border-radius:8px;">Browse Models to Paint</a>
  </div>
</div>

<style>
.cf-community-gallery{{max-width:1200px;margin:0 auto;padding:20px;font-family:'Inter',sans-serif;color:#e8e8e8;text-align:center;}}
.cf-cg-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}}
.cf-gallery-card{{position:relative;border-radius:8px;overflow:hidden;background:#141414;border:1px solid #222;}}
.cf-gallery-card img{{width:100%;height:auto;display:block;}}
.cf-gallery-card__caption{{padding:10px 12px;font-size:11px;color:#888;text-align:left;line-height:1.4;}}
@media(max-width:768px){{.cf-cg-grid{{grid-template-columns:repeat(2,1fr);gap:8px;}}}}
</style>
"""


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    token = get_shopify_token()
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json", "X-Shopify-Access-Token": token})
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    print("\n  Generating community gallery\n")

    image_paths = []
    for i, desc in enumerate(GALLERY_ITEMS):
        print(f"  [{i + 1}/24] {desc[:50]}...", end=" ", flush=True)
        path = try_gemini_image(desc, i)
        if not path:
            path = generate_gallery_image_pil(desc, i)
            print("(PIL)")
        else:
            print("(Gemini)")
        image_paths.append(path)

    # Upload images to Shopify Files
    print("\n  Uploading to Shopify Files...\n")
    gql = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}/graphql.json"
    image_urls = []

    for i, path in enumerate(image_paths):
        file_size = os.path.getsize(path)
        filename = f"gallery-{i + 1:02d}.jpg"

        stage_query = """
        mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
          stagedUploadsCreate(input: $input) {
            stagedTargets { url resourceUrl parameters { name value } }
            userErrors { field message }
          }
        }"""
        stage_vars = {"input": [{"filename": filename, "mimeType": "image/jpeg",
                                  "resource": "FILE", "fileSize": str(file_size), "httpMethod": "POST"}]}
        r = session.post(gql, json={"query": stage_query, "variables": stage_vars}, timeout=30)
        if r.status_code != 200:
            image_urls.append("")
            continue

        data = r.json().get("data", {}).get("stagedUploadsCreate", {})
        target = data.get("stagedTargets", [{}])[0]
        if not target.get("url"):
            image_urls.append("")
            continue

        form_data = {p["name"]: p["value"] for p in target["parameters"]}
        with open(path, "rb") as f:
            files = {"file": (filename, f, "image/jpeg")}
            requests.post(target["url"], data=form_data, files=files, timeout=60)

        create_query = """
        mutation fileCreate($files: [FileCreateInput!]!) {
          fileCreate(files: $files) { files { id } userErrors { field message } }
        }"""
        create_vars = {"files": [{"alt": GALLERY_ITEMS[i], "contentType": "IMAGE",
                                   "originalSource": target["resourceUrl"]}]}
        r = session.post(gql, json={"query": create_query, "variables": create_vars}, timeout=30)
        image_urls.append(target["resourceUrl"])
        print(f"    Uploaded {filename}")
        time.sleep(1)

    # Create the page
    print("\n  Creating gallery page...\n")
    page_html = build_page_html(image_urls)

    r = session.get(f"{base}/pages.json?handle=community-gallery", timeout=15)
    pages = r.json().get("pages", []) if r.status_code == 200 else []
    existing = [p for p in pages if p.get("handle") == "community-gallery"]

    if existing:
        pid = existing[0]["id"]
        session.put(f"{base}/pages/{pid}.json", json={
            "page": {"id": pid, "body_html": page_html, "title": "Community Gallery — Show Us Your Builds"}
        }, timeout=15)
        print(f"  Updated existing page (ID: {pid})")
    else:
        session.post(f"{base}/pages.json", json={
            "page": {"title": "Community Gallery — Show Us Your Builds",
                     "handle": "community-gallery", "body_html": page_html, "published": True}
        }, timeout=15)
        print("  Created /pages/community-gallery")

    print(f"\n  Done! 24 gallery images generated and page created.\n")


if __name__ == "__main__":
    main()
