"""
CastForge Image Processor

Downloads product images, picks the best one using Claude Vision,
then creates branded hero and gallery images.

Usage:
  python main.py process-images <input.csv>           Full processing (rembg + studio)
  python main.py process-images <input.csv> --fast     Vignette + watermark only (10x faster)
"""

import hashlib
import io
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

import config

# ═══════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════

OUTPUT_DIR = Path("processed_images")
CACHE_FILE = Path("image_process_cache.json")
CANVAS_SIZE = (1200, 1200)
BG_COLOR = (13, 13, 13)           # #0D0D0D
AMBER = (245, 158, 11)            # #F59E0B
WATERMARK_OPACITY = 26            # ~10% of 255
VIGNETTE_STRENGTH = 120
MAX_WORKERS = 4


# ═══════════════════════════════════════════════════════════════
# CACHE
# ═══════════════════════════════════════════════════════════════

def _load_cache():
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}


def _save_cache(cache):
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def _url_hash(url):
    return hashlib.md5(url.encode()).hexdigest()[:12]


# ═══════════════════════════════════════════════════════════════
# IMAGE PICKING — Claude Vision scoring
# ═══════════════════════════════════════════════════════════════

PICKER_PROMPT = """Score this product image for e-commerce use on a scale of 1-10.
Evaluate: (1) No Chinese/Japanese/Korean text visible, (2) No watermarks or logos,
(3) Clear product shot with good lighting, (4) Clean background.

Respond in JSON ONLY:
{"score": 7, "has_cjk_text": false, "has_watermark": false, "notes": "brief reason"}"""


def pick_best_image(image_urls, api_key=None):
    """
    Score each image with Claude Vision and return the best one.
    Returns (best_url, scores_dict).
    """
    api_key = api_key or config.ANTHROPIC_API_KEY
    if not api_key or api_key == "sk-ant-xxx" or not image_urls:
        return image_urls[0] if image_urls else "", {}

    scores = {}
    for url in image_urls[:6]:  # Max 6 images to check
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 150,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "url", "url": url}},
                            {"type": "text", "text": PICKER_PROMPT},
                        ],
                    }],
                },
                timeout=30,
            )
            if resp.status_code == 200:
                text = resp.json()["content"][0]["text"].strip()
                if text.startswith("```"):
                    text = re.sub(r"^```(?:json)?\s*", "", text)
                    text = re.sub(r"\s*```$", "", text)
                result = json.loads(text)
                score = result.get("score", 5)
                if result.get("has_cjk_text"):
                    score -= 5
                if result.get("has_watermark"):
                    score -= 3
                scores[url] = score
            time.sleep(0.5)
        except Exception:
            scores[url] = 3  # Default mediocre score on error

    if not scores:
        return image_urls[0], {}

    best = max(scores, key=scores.get)
    return best, scores


# ═══════════════════════════════════════════════════════════════
# IMAGE CREATION HELPERS (require Pillow)
# ═══════════════════════════════════════════════════════════════

def _ensure_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops
        return True
    except ImportError:
        return False


def _download_image(url):
    """Download image and return PIL Image."""
    from PIL import Image
    resp = requests.get(url, timeout=20, headers={"Referer": "https://www.aliexpress.com/"})
    if resp.status_code != 200:
        return None
    return Image.open(io.BytesIO(resp.content)).convert("RGBA")


def _create_vignette(size, strength=VIGNETTE_STRENGTH):
    """Create a dark vignette mask."""
    from PIL import Image, ImageDraw, ImageFilter
    w, h = size
    vignette = Image.new("L", size, 0)
    draw = ImageDraw.Draw(vignette)
    cx, cy = w // 2, h // 2
    max_r = int((w ** 2 + h ** 2) ** 0.5 / 2)
    for r in range(max_r, 0, -2):
        brightness = int(strength * (r / max_r) ** 2)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=brightness)
    return vignette.filter(ImageFilter.GaussianBlur(60))


def _add_watermark(canvas, text="CASTFORGE", opacity=WATERMARK_OPACITY):
    """Add subtle watermark text bottom-right."""
    from PIL import Image, ImageDraw, ImageFont
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
    except (OSError, IOError):
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = canvas.size[0] - tw - 30
    y = canvas.size[1] - th - 25
    draw.text((x, y), text, fill=(*AMBER, opacity), font=font)
    return Image.alpha_composite(canvas.convert("RGBA"), overlay)


def _add_scale_badge(canvas, scale_text):
    """Add scale badge pill bottom-left with amber text on dark bg."""
    if not scale_text:
        return canvas
    from PIL import Image, ImageDraw, ImageFont
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    except (OSError, IOError):
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), scale_text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 12, 6
    x, y = 25, canvas.size[1] - th - pad_y * 2 - 25
    draw.rounded_rectangle(
        [x, y, x + tw + pad_x * 2, y + th + pad_y * 2],
        radius=8, fill=(20, 20, 20, 200),
    )
    draw.text((x + pad_x, y + pad_y), scale_text, fill=(*AMBER, 230), font=font)
    return Image.alpha_composite(canvas.convert("RGBA"), overlay)


# ═══════════════════════════════════════════════════════════════
# HERO IMAGE (position 1) — full studio treatment
# ═══════════════════════════════════════════════════════════════

def create_hero_image(image_url, scale_text="", output_path=None):
    """
    Full hero image: rembg background removal → dark studio canvas →
    amber glow → drop shadow → vignette → watermark → scale badge.
    """
    from PIL import Image, ImageDraw, ImageFilter, ImageChops

    original = _download_image(image_url)
    if original is None:
        return None

    # Background removal
    try:
        from rembg import remove as rembg_remove
        product = rembg_remove(original)
    except Exception:
        product = original

    # Dark studio canvas
    canvas = Image.new("RGB", CANVAS_SIZE, BG_COLOR)

    # Subtle radial gradient (ambient light)
    gradient = Image.new("L", CANVAS_SIZE, 0)
    draw = ImageDraw.Draw(gradient)
    cx, cy = CANVAS_SIZE[0] // 2, CANVAS_SIZE[1] // 2
    for r in range(min(CANVAS_SIZE) // 2, 0, -4):
        brightness = int(25 * (1 - r / (min(CANVAS_SIZE) // 2)))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=brightness)
    gradient = gradient.filter(ImageFilter.GaussianBlur(80))
    grad_rgb = Image.merge("RGB", [gradient, gradient, gradient])
    canvas = ImageChops.add(canvas, grad_rgb)

    # Amber glow behind product
    glow = Image.new("RGB", CANVAS_SIZE, BG_COLOR)
    glow_draw = ImageDraw.Draw(glow)
    for r in range(300, 0, -3):
        alpha = int(8 * (1 - r / 300))
        glow_draw.ellipse([cx - r, cy - r + 40, cx + r, cy + r + 40],
                          fill=(BG_COLOR[0] + alpha * 3, BG_COLOR[1] + alpha * 2, BG_COLOR[2]))
    glow = glow.filter(ImageFilter.GaussianBlur(50))
    canvas = ImageChops.lighter(canvas, glow)

    # Scale product to 75%, slight upward offset
    max_dim = int(CANVAS_SIZE[0] * 0.75)
    product.thumbnail((max_dim, max_dim), Image.LANCZOS)
    pw, ph = product.size
    x = (CANVAS_SIZE[0] - pw) // 2
    y = (CANVAS_SIZE[1] - ph) // 2 - 30

    # Drop shadow
    shadow = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    shadow.paste(product, (x + 5, y + 8))
    shadow_blur = shadow.filter(ImageFilter.GaussianBlur(15))
    shadow_canvas = Image.new("RGB", CANVAS_SIZE, BG_COLOR)
    shadow_canvas.paste(shadow_blur, mask=shadow_blur.split()[3])
    canvas = Image.composite(canvas, shadow_canvas, Image.new("L", CANVAS_SIZE, 200))

    # Paste product
    canvas.paste(product, (x, y), product if product.mode == "RGBA" else None)

    # Vignette
    vignette = _create_vignette(CANVAS_SIZE)
    vignette_rgb = Image.merge("RGB", [vignette, vignette, vignette])
    canvas = ImageChops.subtract(canvas, vignette_rgb)

    # Watermark + scale badge
    canvas = _add_watermark(canvas)
    canvas = _add_scale_badge(canvas, scale_text)

    # Save
    final = canvas.convert("RGB")
    if output_path:
        final.save(output_path, "JPEG", quality=92)
    return final


# ═══════════════════════════════════════════════════════════════
# GALLERY IMAGE (positions 2-6) — light treatment
# ═══════════════════════════════════════════════════════════════

def create_gallery_image(image_url, output_path=None):
    """
    Gallery image: original image + dark vignette overlay + tiny watermark.
    No background removal — fast and consistent.
    """
    from PIL import Image, ImageChops

    original = _download_image(image_url)
    if original is None:
        return None

    # Resize to canvas
    img = original.convert("RGB")
    img.thumbnail(CANVAS_SIZE, Image.LANCZOS)

    # Center on dark canvas if smaller
    canvas = Image.new("RGB", CANVAS_SIZE, BG_COLOR)
    x = (CANVAS_SIZE[0] - img.size[0]) // 2
    y = (CANVAS_SIZE[1] - img.size[1]) // 2
    canvas.paste(img, (x, y))

    # Vignette
    vignette = _create_vignette(CANVAS_SIZE, strength=80)
    vignette_rgb = Image.merge("RGB", [vignette, vignette, vignette])
    canvas = ImageChops.subtract(canvas, vignette_rgb)

    # Watermark
    canvas = _add_watermark(canvas, opacity=20)

    final = canvas.convert("RGB")
    if output_path:
        final.save(output_path, "JPEG", quality=90)
    return final


# ═══════════════════════════════════════════════════════════════
# FAST MODE — no rembg, just vignette + watermark + badge
# ═══════════════════════════════════════════════════════════════

def create_fast_image(image_url, scale_text="", output_path=None):
    """Fast mode: resize original + vignette + watermark + scale badge."""
    from PIL import Image, ImageChops

    original = _download_image(image_url)
    if original is None:
        return None

    img = original.convert("RGB")
    img.thumbnail(CANVAS_SIZE, Image.LANCZOS)

    canvas = Image.new("RGB", CANVAS_SIZE, BG_COLOR)
    x = (CANVAS_SIZE[0] - img.size[0]) // 2
    y = (CANVAS_SIZE[1] - img.size[1]) // 2
    canvas.paste(img, (x, y))

    vignette = _create_vignette(CANVAS_SIZE)
    vignette_rgb = Image.merge("RGB", [vignette, vignette, vignette])
    canvas = ImageChops.subtract(canvas, vignette_rgb)

    canvas = _add_watermark(canvas)
    canvas = _add_scale_badge(canvas, scale_text)

    final = canvas.convert("RGB")
    if output_path:
        final.save(output_path, "JPEG", quality=92)
    return final


# ═══════════════════════════════════════════════════════════════
# BATCH PROCESSOR — parallel with threading
# ═══════════════════════════════════════════════════════════════

def process_product_images(product, index, fast=False, api_key=None):
    """
    Process all images for a single product.
    Returns dict of {position: local_path}.
    """
    cache = _load_cache()
    cache_key = _url_hash(product.get("image_url", "") or product.get("title", ""))

    if cache_key in cache:
        return cache[cache_key]

    OUTPUT_DIR.mkdir(exist_ok=True)
    slug = re.sub(r"[^a-z0-9]", "-", product.get("title", "img")[:30].lower()).strip("-")
    scale = ""
    m = re.search(r"1[:/](\d{1,3})", product.get("title", ""))
    if m:
        scale = f"1/{m.group(1)}"
    else:
        m = re.search(r"(\d{2,3})\s*mm", product.get("title", ""), re.IGNORECASE)
        if m:
            scale = f"{m.group(1)}mm"

    # Collect all image URLs
    all_images = []
    main_img = product.get("image_url", "")
    if main_img:
        all_images.append(main_img)
    images_raw = product.get("images", "")
    if images_raw:
        for img in images_raw.split("|"):
            img = img.strip()
            if img and img not in all_images:
                all_images.append(img)

    if not all_images:
        return {}

    # Pick best image for hero (position 1)
    best_url = all_images[0]
    if len(all_images) > 1 and api_key and api_key != "sk-ant-xxx":
        best_url, _ = pick_best_image(all_images, api_key)

    results = {}

    # Hero image
    hero_path = str(OUTPUT_DIR / f"{index:04d}_{slug}_hero.jpg")
    try:
        if fast:
            create_fast_image(best_url, scale, hero_path)
        else:
            create_hero_image(best_url, scale, hero_path)
        results["1"] = hero_path
    except Exception as e:
        print(f"    Hero failed for {slug}: {str(e)[:60]}")

    # Gallery images (positions 2-6)
    gallery_urls = [u for u in all_images if u != best_url][:5]
    for i, gurl in enumerate(gallery_urls, start=2):
        gallery_path = str(OUTPUT_DIR / f"{index:04d}_{slug}_gallery{i}.jpg")
        try:
            create_gallery_image(gurl, gallery_path)
            results[str(i)] = gallery_path
        except Exception:
            pass

    # Cache
    cache[cache_key] = results
    _save_cache(cache)

    return results


def process_batch(products, fast=False, api_key=None):
    """Process images for all products using thread pool."""
    if not _ensure_pillow():
        print("  Pillow is required: pip install Pillow")
        if not fast:
            print("  For full mode, also: pip install rembg onnxruntime")
        return {}

    total = len(products)
    all_results = {}
    success = 0
    failed = 0

    print(f"\n  Processing {total} products ({'FAST' if fast else 'FULL'} mode, {MAX_WORKERS} threads)...\n")

    def _process_one(args):
        idx, product = args
        return idx, process_product_images(product, idx, fast=fast, api_key=api_key)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_process_one, (i, p)): i for i, p in enumerate(products)}
        for future in as_completed(futures):
            try:
                idx, result = future.result()
                if result:
                    all_results[idx] = result
                    success += 1
                else:
                    failed += 1
            except Exception:
                failed += 1

            done = success + failed
            if done % 20 == 0 or done == total:
                print(f"  [{done}/{total}] {success} OK, {failed} failed")

    print(f"\n  Done: {success} processed, {failed} failed")
    return all_results
