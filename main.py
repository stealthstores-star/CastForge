#!/usr/bin/env python3
"""
CastForge Pipeline CLI

Commands:
  python main.py comply <input.csv>             — Run title compliance scan only
  python main.py comply-images <input.csv>      — Scan images via Claude Vision
  python main.py upload <input.csv>             — Full pipeline: comply → categorize → upload
  python main.py export <input.csv> [--fast]    — Comply → categorize → Shopify CSV export
  python main.py process-images <input.csv>     — Download + process images (rembg)
  python main.py stats <input.csv>              — Show category breakdown (no upload)
  python main.py scrape <urls.txt>              — Scrape AliExpress URLs to CSV
  python main.py audit                          — Audit existing Shopify products
"""

import base64
import csv
import hashlib
import io
import json
import math
import sys
import time
from pathlib import Path
import os
import re

import requests

import config
import compliance
import categorizer
import seo as seo_module
from uploader import ShopifyUploader
from exporter import export_shopify_csv


# ═══════════════════════════════════════════════════════════════
# CSV LOADING (auto-detect column names)
# ═══════════════════════════════════════════════════════════════

COLUMN_ALIASES = {
    "title": ["product_title", "title", "name", "product_name"],
    "price": ["product_price", "price", "cost", "ali_price"],
    "image_url": ["product_image", "image_url", "main_image", "image", "Image Src"],
    "images": ["product_images", "images", "additional_images"],
    "url": ["product_url", "url", "link", "source_url"],
    "shipping": ["shipping", "shipping_cost", "ship_cost"],
}


def _detect_column(headers, field):
    """Find the best matching column name for a field."""
    aliases = COLUMN_ALIASES.get(field, [field])
    for alias in aliases:
        for h in headers:
            if h.lower().strip() == alias.lower():
                return h
    return None


def load_csv(path):
    """Load AliExpress CSV with auto-detected column names."""
    products = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames

        col_title = _detect_column(headers, "title")
        col_price = _detect_column(headers, "price")
        col_image = _detect_column(headers, "image_url")
        col_images = _detect_column(headers, "images")
        col_url = _detect_column(headers, "url")
        col_shipping = _detect_column(headers, "shipping")

        if not col_title:
            print(f"Error: No title column found. Headers: {headers}")
            sys.exit(1)

        print(f"  Column mapping:")
        print(f"    title    → {col_title}")
        print(f"    price    → {col_price or '(not found)'}")
        print(f"    image    → {col_image or '(not found)'}")
        print(f"    images   → {col_images or '(not found)'}")
        print(f"    shipping → {col_shipping or '(not found)'}")

        for row in reader:
            raw_title = row.get(col_title, "").strip()
            product = {
                "title": raw_title,
                "_original_title": raw_title,  # preserved untouched through pipeline
                "raw_price": row.get(col_price, "0") if col_price else "0",
                "image_url": row.get(col_image, "") if col_image else "",
                "images": row.get(col_images, "") if col_images else "",
                "source_url": row.get(col_url, "") if col_url else "",
                "raw_shipping": row.get(col_shipping, "0") if col_shipping else "0",
                "variations": row.get("variations", ""),
                "variation_images": row.get("variation_images", ""),
            }
            if product["title"]:
                products.append(product)

    # Debug: show image data for first product
    if products:
        p0 = products[0]
        img = p0.get("image_url", "")
        imgs = p0.get("images", "")
        print(f"  First product images:")
        print(f"    image_url: {img[:80] if img else 'EMPTY'}")
        print(f"    images: {imgs[:80] if imgs else 'EMPTY'}")

    print(f"  Loaded {len(products)} products from {path}\n")
    return products


# ═══════════════════════════════════════════════════════════════
# PRICING
# ═══════════════════════════════════════════════════════════════

def _parse_price(raw):
    """Parse price from various formats: £3.12, ￡3.61, US $5.99, ￡3.61 50% off￡7.22."""
    if not raw:
        return 0.0
    s = str(raw)
    # Normalise full-width pound ￡ (U+FFE1) to regular £
    s = s.replace("\uffe1", "£")
    # Look for first price after a currency symbol
    m = re.search(r"[£$€]\s*(\d+\.?\d*)", s)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    # Fallback: first bare number
    m = re.search(r"(\d+\.?\d*)", s)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return 0.0
    return 0.0


def _round_to_99(price):
    """Round to nearest .99 (e.g. 24.37 → 24.99, 25.10 → 25.99)."""
    return math.floor(price) + 0.99


def calculate_price(product_price_gbp, shipping_gbp):
    """
    Apply the CastForge pricing formula.
    Returns (selling_price_usd, compare_at_price_usd).
    """
    total_cost = product_price_gbp + shipping_gbp

    price_a = (total_cost + 7.50) / 0.95
    price_b = total_cost / 0.60
    selling_gbp = max(price_a, price_b)

    selling_usd = selling_gbp * config.GBP_TO_USD

    if config.ROUND_TO_99:
        selling_usd = _round_to_99(selling_usd)

    selling_usd = max(selling_usd, config.MIN_PRICE_USD)

    compare_at_usd = selling_usd * config.COMPARE_AT_MULTIPLIER
    if config.ROUND_TO_99:
        compare_at_usd = _round_to_99(compare_at_usd)

    return round(selling_usd, 2), round(compare_at_usd, 2)


# ═══════════════════════════════════════════════════════════════
# DUPLICATE DETECTION
# ═══════════════════════════════════════════════════════════════

def _normalise_for_dedup(title):
    """Reduce a title to a canonical form for duplicate detection.
    Keep scale and meaningful descriptors — only strip AliExpress spam."""
    t = title.lower().strip()
    # Only strip the most generic filler, NOT descriptive words
    t = re.sub(r"\b(resin|model|kit|diy|craft|toys?|collectib\w*|"
               r"handmade|unpainted|unassembled|colorless|self-assembled|"
               r"self assembled)\b", "", t)
    t = re.sub(r"[^a-z0-9]", "", t)  # letters + digits
    return t


def _image_fingerprint(url):
    """Extract a stable fingerprint from an image URL (AliExpress CDN hash)."""
    m = re.search(r"/([A-Za-z0-9]{30,})\.", url)
    if m:
        return m.group(1).lower()
    return hashlib.md5(url.encode()).hexdigest()


def deduplicate(products):
    """
    Remove duplicate products. A product is a duplicate only if BOTH:
      1. Its normalised title matches another product, AND
      2. Its primary image CDN hash matches that same product.
    Two products with different images are NEVER duplicates.
    Returns (unique_products, duplicate_count).
    """
    seen = {}  # key: (norm_title, img_fingerprint)
    unique = []
    dupes = 0

    for p in products:
        title = p.get("title", "")
        norm = _normalise_for_dedup(title)
        img = p.get("image_url", "")
        img_fp = _image_fingerprint(img) if img else ""

        dedup_key = (norm, img_fp)

        if norm and img_fp and dedup_key in seen:
            dupes += 1
            continue

        if norm and img_fp:
            seen[dedup_key] = title
        unique.append(p)

    if dupes:
        print(f"  Dedup: removed {dupes} duplicates, {len(unique)} unique products remain")
    return unique, dupes


# ═══════════════════════════════════════════════════════════════
# PRODUCT PROCESSING (shared between export/upload)
# ═══════════════════════════════════════════════════════════════

def process_products(products):
    """
    Run the full processing pipeline on a list of raw products:
    compliance → dedup → categorize → price → SEO.
    Returns (export_ready, blocked, dupes_removed).
    """
    # Step 1: Compliance
    print("  Running compliance scan...")
    blocked, warnings, clean, changed = compliance.compliance_report(products)
    compliance.write_report(blocked, warnings, clean, changed)
    print(f"  Blocked: {len(blocked)}, Changed: {len(changed)}, Clean: {len(clean)}")

    uploadable = clean + changed
    if not uploadable:
        return [], blocked, 0

    # Step 2: Dedup
    uploadable, dupes_removed = deduplicate(uploadable)

    # Step 3: Categorize + Price + SEO
    print(f"  Categorizing and pricing {len(uploadable)} products...")
    export_products = []
    category_counts = {}
    sku_counter = 1

    # First pass: keyword categorization
    needs_ai = []  # (index, raw_title) for products with score < 2

    for p in uploadable:
        raw_title = p.get("_original_title", p["title"])
        handle, score, parent = categorizer.categorize(raw_title)
        scale = categorizer.detect_scale(raw_title)

        price_gbp = _parse_price(p.get("raw_price", "0"))
        shipping_gbp = _parse_price(p.get("raw_shipping", "0"))
        sell_usd, compare_usd = calculate_price(price_gbp, shipping_gbp)

        # Images: use pipe-separated list, fall back to main image
        image_url = p.get("image_url", "")
        images_raw = p.get("images", "")
        if images_raw:
            first_full = images_raw.split("|")[0].strip()
            if first_full:
                image_url = first_full
        elif not image_url:
            # Check if compliance spread lost the image fields
            image_url = p.get("product_image", "")
            images_raw = p.get("product_images", "")

        # Debug: first 3 products
        if len(export_products) < 3:
            total_cost = price_gbp + shipping_gbp
            pa = (total_cost + 7.50) / 0.95
            pb = total_cost / 0.60
            print(f"    Product {len(export_products)+1}: "
                  f"price=£{price_gbp:.2f} ship=£{shipping_gbp:.2f} "
                  f"A=£{pa:.2f} B=£{pb:.2f} → ${sell_usd:.2f} | "
                  f"img={bool(image_url)} "
                  f"extras={len(images_raw.split('|')) if images_raw else 0} | "
                  f"raw_price=\"{p.get('raw_price', '')[:20]}\"")


        product_data = {
            "_raw_title": raw_title,
            "_score": score,
            "title": "",  # filled after AI pass
            "body_html": "",
            "product_type": "",
            "tags": [],
            "price": sell_usd,
            "compare_at_price": compare_usd,
            "image_url": image_url,
            "images": images_raw,
            "category_handle": handle,
            "parent_handle": parent,
            "seo_title": "",
            "seo_description": "",
            "handle": "",
            "sku": f"CF-{sku_counter:06d}",
            "variations": p.get("variations", ""),
            "variation_images": p.get("variation_images", ""),
        }
        export_products.append(product_data)

        if score < 2:
            needs_ai.append(product_data)

        sku_counter += 1

    # Categorization is now pure keyword — no AI calls needed
    # (ai_categorize_batch removed — keywords handle everything)

    # Second pass: generate titles, descriptions, SEO with final categories
    for product_data in export_products:
        handle = product_data["category_handle"]
        parent = product_data["parent_handle"]
        raw_title = product_data["_raw_title"]
        scale = categorizer.detect_scale(raw_title)

        title = categorizer.clean_title(raw_title, handle)
        body_html = categorizer.generate_description(title, handle, scale)
        parent_name = categorizer.PARENT_DISPLAY_NAMES.get(parent, "Diorama & Terrain") if parent else "Diorama & Terrain"
        seo_data = seo_module.generate_seo(title, handle)

        product_data["title"] = title
        product_data["body_html"] = body_html
        product_data["product_type"] = parent_name
        product_data["tags"] = seo_data["tags"]
        product_data["seo_title"] = seo_data["seo_title"]
        product_data["seo_description"] = seo_data["seo_description"]
        product_data["handle"] = seo_data["handle"]

        category_counts[handle] = category_counts.get(handle, 0) + 1

    # AI title generation (disabled — too slow and unreliable)
    _ai_key = config.ANTHROPIC_API_KEY
    if _ai_key and _ai_key != "sk-ant-xxx":
        categorizer.ai_generate_titles_batch(export_products, _ai_key)
        for product_data in export_products:
            if "_raw_title" in product_data:
                handle = product_data["category_handle"]
                title = product_data["title"]
                scale = categorizer.detect_scale(product_data["_raw_title"])
                seo_data = seo_module.generate_seo(title, handle)
                product_data["body_html"] = categorizer.generate_description(title, handle, scale)
                product_data["seo_title"] = seo_data["seo_title"]
                product_data["seo_description"] = seo_data["seo_description"]
                product_data["handle"] = seo_data["handle"]
                product_data["tags"] = seo_data["tags"]

    # Clean up internal fields
    for product_data in export_products:
        product_data.pop("_raw_title", None)
        product_data.pop("_original_title", None)
        product_data.pop("_score", None)

    # Category breakdown
    print(f"\n  {'Category':<35} {'Count':>5}")
    print(f"  {'-'*40}")
    for h in sorted(category_counts, key=category_counts.get, reverse=True):
        name = categorizer.CATEGORY_DISPLAY_NAMES.get(h, h)
        print(f"  {name:<35} {category_counts[h]:>5}")

    # Fix image URLs for Shopify compatibility
    fix_product_image_urls(export_products)

    # Write needs_review.csv if any products couldn't be categorized
    categorizer.write_needs_review()

    return export_products, blocked, dupes_removed


# ═══════════════════════════════════════════════════════════════
# IMAGE URL FIXER
# ═══════════════════════════════════════════════════════════════

def _fix_image_url(url):
    """
    Fix AliExpress image URL for Shopify compatibility:
    1. Convert ae-pic-a1.aliexpress-media.com → ae01.alicdn.com
    2. Strip thumbnail suffix (_350x350.jpg, _480x480.jpg)
    3. Ensure full-size .jpg URL
    """
    if not url:
        return url

    # Fix CDN domain: aliexpress-media → alicdn
    url = re.sub(
        r"https?://ae-pic-a1\.aliexpress-media\.com/kf/",
        "https://ae01.alicdn.com/kf/",
        url,
    )

    # Strip thumbnail size suffix: .jpg_350x350.jpg → .jpg
    url = re.sub(r"(\.\w{3,4})_\d+x\d+\.\w+$", r"\1", url)

    # Ensure https
    if url.startswith("//"):
        url = f"https:{url}"

    return url


def _is_valid_product_image(url):
    """Check if an image URL is a valid product photo (not junk)."""
    if not url:
        return False
    # Must be from alicdn.com/kf/
    if "alicdn.com/kf/" not in url:
        return False
    # Must be .jpg/.jpeg (skip .png — logos/watermarks)
    if not re.search(r"\.jpe?g$", url, re.IGNORECASE):
        return False
    # No dimension patterns in URL path (icon sizes like /27x27/)
    if re.search(r"/\d+x\d+", url):
        return False
    # Skip junk URLs by content indicators in the path
    junk_indicators = ["desc", "description", "banner", "shop", "store",
                        "logo", "icon", "review", "feedback", "rating",
                        "point", "star", "shipping", "delivery",
                        "customer", "service"]
    url_lower = url.lower()
    if any(ind in url_lower for ind in junk_indicators):
        return False
    return True


def fix_product_image_urls(products):
    """Fix CDN URLs only. NO filtering, NO reordering. Pass through as-is."""
    for product in products:
        # Fix main image URL
        main = product.get("image_url", "")
        if main:
            product["image_url"] = _fix_image_url(main)

        # Fix additional image URLs — keep exact order from scraper
        images_raw = product.get("images", "")
        if images_raw:
            urls = [u.strip() for u in images_raw.split("|") if u.strip()]
            fixed_urls = [_fix_image_url(u) for u in urls]
            # Only filter: skip completely empty/null URLs
            fixed_urls = [u for u in fixed_urls if u]
            product["images"] = "|".join(fixed_urls)
            # Set main image to first from list if not already set
            if fixed_urls and not product.get("image_url"):
                product["image_url"] = fixed_urls[0]


# ═══════════════════════════════════════════════════════════════
# COMMANDS
# ═══════════════════════════════════════════════════════════════

def cmd_comply(csv_path):
    """Run title compliance scan only."""
    print("\n══════════════════════════════════════")
    print("  CastForge Title Compliance Scan")
    print("══════════════════════════════════════\n")

    products = load_csv(csv_path)
    # Normalize for compliance module
    for p in products:
        p["title"] = p.get("title", "")
    blocked, warnings, clean, changed = compliance.compliance_report(products)
    compliance.write_report(blocked, warnings, clean, changed)

    print(f"\n{'='*50}")
    print(f"  Blocked:        {len(blocked)}")
    print(f"  Title changes:  {len(changed)}")
    print(f"  Warnings:       {len(warnings)}")
    print(f"  Clean:          {len(clean)}")
    print(f"{'='*50}")


def cmd_comply_images(csv_path):
    """Run image compliance scan via Claude Vision."""
    print("\n══════════════════════════════════════")
    print("  CastForge Image Compliance Scan")
    print("══════════════════════════════════════\n")

    if config.ANTHROPIC_API_KEY == "sk-ant-xxx":
        print("Set ANTHROPIC_API_KEY environment variable to scan images.")
        sys.exit(1)

    products = load_csv(csv_path)
    image_urls = [p["image_url"] for p in products if p.get("image_url")]

    print(f"Found {len(image_urls)} images to scan\n")
    image_results = compliance.scan_images_batch(image_urls)
    blocked, warnings, clean, changed = compliance.compliance_report(products, image_results)
    compliance.write_report(blocked, warnings, clean, changed)

    print(f"\n{'='*50}")
    print(f"  Blocked:        {len(blocked)}")
    print(f"  Title changes:  {len(changed)}")
    print(f"  Image warnings: {len(warnings)}")
    print(f"  Clean:          {len(clean)}")
    print(f"{'='*50}")


def cmd_stats(csv_path):
    """Show category breakdown without uploading."""
    print("\n══════════════════════════════════════")
    print("  CastForge Category Stats")
    print("══════════════════════════════════════\n")

    products = load_csv(csv_path)
    counts = {}
    uncategorized = []

    for p in products:
        handle, score, parent = categorizer.categorize(p["title"])
        clean_t = categorizer.clean_title(p["title"], handle)
        counts[handle] = counts.get(handle, 0) + 1
        if handle == "uncategorized":
            uncategorized.append(clean_t)

    print(f"  {'Category':<35} {'Count':>5}")
    print(f"  {'-'*40}")
    for handle in sorted(counts, key=counts.get, reverse=True):
        name = categorizer.CATEGORY_DISPLAY_NAMES.get(handle, handle)
        print(f"  {name:<35} {counts[handle]:>5}")

    if uncategorized:
        print(f"\n  Uncategorized products ({len(uncategorized)}):")
        for t in uncategorized[:20]:
            print(f"    - {t[:70]}")


def cmd_nuke():
    """Delete ALL products from Shopify."""
    print("\n══════════════════════════════════════")
    print("  CastForge Nuke — Delete All Products")
    print("══════════════════════════════════════\n")
    from uploader import nuke_all_products
    nuke_all_products()


UPLOAD_PROGRESS_FILE = Path("upload_progress.json")
CHUNK_SIZE = 1000


def _load_upload_progress():
    if UPLOAD_PROGRESS_FILE.exists():
        return json.loads(UPLOAD_PROGRESS_FILE.read_text())
    return {"uploaded_urls": [], "product_ids": [], "chunks_done": 0,
            "total_success": 0, "total_failed": 0}


def _save_upload_progress(progress):
    UPLOAD_PROGRESS_FILE.write_text(json.dumps(progress, indent=2))


def cmd_upload(csv_path, resume=False):
    """Chunked upload: process all → upload in chunks of 1000 with auto-resume."""
    print("\n╔══════════════════════════════════════╗")
    print("║  CastForge Chunked Upload Pipeline   ║")
    print("╚══════════════════════════════════════╝\n")

    # Step 1: Load + process ALL products at once
    print("Step 1: Loading CSV...")
    products = load_csv(csv_path)

    print("Step 2: Processing all products (compliance/categorize/pricing/titles)...")
    upload_ready, blocked, dupes = process_products(products)

    if not upload_ready:
        print("\nNo products passed compliance.")
        return

    print(f"\n  Ready to upload: {len(upload_ready)} products in "
          f"{math.ceil(len(upload_ready) / CHUNK_SIZE)} chunks of {CHUNK_SIZE}")

    # Load resume state
    progress = _load_upload_progress() if resume else {
        "uploaded_urls": [], "product_ids": [], "chunks_done": 0,
        "total_success": 0, "total_failed": 0,
    }

    # Filter out already-uploaded if resuming
    if resume and progress["uploaded_urls"]:
        already = set(progress["uploaded_urls"])
        before = len(upload_ready)
        upload_ready = [p for p in upload_ready if p.get("source_url", "") not in already]
        print(f"  Resume: skipping {before - len(upload_ready)} already uploaded, "
              f"{len(upload_ready)} remaining")

    # Step 3: Upload in chunks
    total_chunks = math.ceil(len(upload_ready) / CHUNK_SIZE)
    print(f"\nStep 3: Uploading {len(upload_ready)} products in {total_chunks} chunks...\n")

    uploader = ShopifyUploader()
    start_time = time.time()

    for chunk_idx in range(total_chunks):
        chunk_start = chunk_idx * CHUNK_SIZE
        chunk = upload_ready[chunk_start:chunk_start + CHUNK_SIZE]

        uploader.upload_chunk(chunk, chunk_idx + 1, total_chunks)

        # Track uploaded URLs for resume
        for p in chunk:
            url = p.get("source_url", "")
            if url:
                progress["uploaded_urls"].append(url)

        progress["product_ids"].extend(uploader.results["product_ids"][-len(chunk):])
        progress["chunks_done"] = chunk_idx + 1
        progress["total_success"] = uploader.results["success"]
        progress["total_failed"] = uploader.results["failed"]
        _save_upload_progress(progress)

        elapsed = time.time() - start_time
        rate = uploader.results["success"] / max(elapsed, 1) * 60
        remaining_chunks = total_chunks - chunk_idx - 1
        print(f"  Chunk {chunk_idx + 1}/{total_chunks}: "
              f"{uploader.results['success']} OK, {uploader.results['failed']} failed | "
              f"{rate:.0f}/min")

    uploader.print_summary()
    uploader.save_failed()

    # Save final upload log
    with open("upload_log.json", "w") as f:
        json.dump({
            "total": len(upload_ready),
            "success": uploader.results["success"],
            "failed": uploader.results["failed"],
            "product_ids": uploader.results["product_ids"],
            "blocked_count": len(blocked),
        }, f, indent=2)
    print("  Saved upload_log.json")


def cmd_audit():
    """Audit all existing Shopify products for compliance issues."""
    print("\n══════════════════════════════════════")
    print("  CastForge Product Audit")
    print("══════════════════════════════════════\n")

    from uploader import get_shopify_token
    token = get_shopify_token()
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base_url = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    products = []
    url = f"{base_url}/products.json?limit=250&fields=id,title,handle,status"
    while url:
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            print(f"API error: {resp.status_code}")
            sys.exit(1)
        data = resp.json()
        products.extend(data.get("products", []))
        link = resp.headers.get("Link", "")
        url = None
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.split("<")[1].split(">")[0]

    print(f"Fetched {len(products)} products from Shopify\n")

    issues_found = []
    for p in products:
        title = p.get("title", "")
        new_title, issues, action = compliance.scan_title(title)
        if issues:
            issues_found.append({
                "id": p["id"],
                "handle": p.get("handle", ""),
                "status": p.get("status", ""),
                "original_title": title,
                "new_title": new_title,
                "action": action,
                "issues": issues,
            })

    print(f"Products with issues: {len(issues_found)}/{len(products)}\n")
    for item in issues_found:
        flag = "BLOCK" if item["action"] == "block" else "FIX"
        print(f"  [{flag}] {item['original_title'][:60]}")
        print(f"         → {item['new_title'][:60]}")
        for issue in item["issues"]:
            print(f"           {issue}")
        print()

    if issues_found:
        with open("audit_results.json", "w") as f:
            json.dump(issues_found, f, indent=2)
        print(f"Saved audit_results.json ({len(issues_found)} issues)")


def cmd_export(csv_path, fast=False):
    """Comply → dedup → categorize → price → export Shopify-compatible CSV."""
    mode = "FAST" if fast else "FULL"
    print(f"\n╔══════════════════════════════════════╗")
    print(f"║  CastForge CSV Export ({mode:4s} mode)    ║")
    print(f"╚══════════════════════════════════════╝\n")
    if fast:
        print("  --fast: skipping image processing, using original images as-is\n")

    print("Step 1: Loading CSV...")
    products = load_csv(csv_path)

    print("Step 2: Processing products...")
    export_products, blocked, dupes = process_products(products)

    if not export_products:
        print("\nNo products passed compliance.")
        return

    # Fix image URLs for Shopify compatibility
    print(f"\nStep 3: Fixing image URLs...")
    fix_product_image_urls(export_products)

    # Export
    output_path = csv_path.replace(".csv", "_shopify_import.csv")
    if output_path == csv_path:
        output_path = "shopify_import.csv"

    print(f"\nStep 4: Exporting Shopify CSV...")
    export_shopify_csv(export_products, output_path)

    print(f"\n  {'='*50}")
    print(f"  Export complete!")
    print(f"  Products:    {len(export_products)}")
    print(f"  Blocked:     {len(blocked)}")
    print(f"  Duplicates:  {dupes}")
    print(f"  Output:      {output_path}")
    print(f"  {'='*50}")
    print(f"\n  Import via: Shopify Admin → Products → Import → {output_path}")


def cmd_process_images(csv_path, fast=False):
    """Download and process product images (hero + gallery)."""
    print("\n══════════════════════════════════════")
    print(f"  CastForge Image Processor ({'FAST' if fast else 'FULL'})")
    print("══════════════════════════════════════\n")

    import image_processor
    products = load_csv(csv_path)
    api_key = config.ANTHROPIC_API_KEY if config.ANTHROPIC_API_KEY != "sk-ant-xxx" else None
    image_processor.process_batch(products, fast=fast, api_key=api_key)


def cmd_scrape(urls_file, limit=None, debug=False, speed="safe"):
    """Scrape AliExpress product URLs to CSV."""
    print("\n══════════════════════════════════════")
    print("  CastForge AliExpress Scraper")
    print("══════════════════════════════════════\n")

    from scraper import scrape_urls
    output = urls_file.replace(".txt", "_scraped.csv")
    if output == urls_file:
        output = "scraped_products.csv"
    scrape_urls(urls_file, output, limit=limit, debug=debug, speed=speed)


def cmd_fix_titles(use_proxy=False):
    """
    Fix 'Aliexpress' titles in scrape_checkpoint.json.
    --proxy: use IPRoyal rotating residential proxy with 60 contexts.
    """
    import asyncio

    checkpoint_path = Path("scrape_checkpoint.json")
    if not checkpoint_path.exists():
        print("No scrape_checkpoint.json found.")
        return

    data = json.loads(checkpoint_path.read_text())
    products = data.get("products", [])

    needs_fix = []
    for i, p in enumerate(products):
        title = p.get("product_title", "")
        if not title or title.lower() in ["aliexpress", "ali express", "aliexpress.com", ""] \
                or "aliexpress" in title.lower()[:15]:
            url = p.get("product_url") or p.get("source_url", "")
            if url:
                needs_fix.append((i, url))

    ctx_count = 60 if use_proxy else 15

    print(f"\n══════════════════════════════════════")
    print(f"  CastForge Title Fixer")
    print(f"══════════════════════════════════════\n")
    print(f"  Total products: {len(products)}")
    print(f"  Need title fix: {len(needs_fix)}")
    print(f"  Contexts: {ctx_count}" + (" (proxy)" if use_proxy else ""))
    if use_proxy:
        print(f"  Proxy: IPRoyal rotating residential (US)")

    if not needs_fix:
        print("  Nothing to fix!")
        return

    est_rate = ctx_count * 12  # ~12 pages/min per context
    print(f"  Estimated: {len(needs_fix) / est_rate:.0f} minutes (~{est_rate}/min)\n")

    fixed = asyncio.run(_run_title_fixer(needs_fix, products,
                                          use_proxy=use_proxy, ctx_count=ctx_count))

    data["products"] = products
    checkpoint_path.write_text(json.dumps(data, ensure_ascii=False))
    print(f"\n  Checkpoint saved: {fixed} titles fixed")


async def _run_title_fixer(needs_fix, products, use_proxy=False, ctx_count=15):
    """Async title fixer with concurrent contexts. Optional proxy."""
    from playwright.async_api import async_playwright
    from scraper import STEALTH_JS, USER_AGENTS, SESSION_FILE

    BATCH_PER_CONTEXT = 50
    BROWSER_RESTART = 1500

    # Proxy config
    proxy_config = None
    if use_proxy:
        proxy_config = {
            "server": "http://geo.iproyal.com:12321",
            "username": "jpo1c9lb5mytbj0t",
            "password": "GnXsjzZq15h0WEdY_country-us",
        }

    fixed_total = 0
    start_time = time.time()

    async with async_playwright() as pw:
        session_path = str(SESSION_FILE) if SESSION_FILE.exists() else None

        launch_args = {
            "headless": True,
            "args": ["--disable-blink-features=AutomationControlled",
                     "--no-sandbox", "--disable-dev-shm-usage"],
        }
        if proxy_config:
            launch_args["proxy"] = proxy_config

        browser = await pw.chromium.launch(**launch_args)

        progress = {"done": 0, "fixed": 0, "failed": 0,
                    "total": len(needs_fix), "start": start_time}

        titles_since_restart = 0

        for cycle_start in range(0, len(needs_fix), ctx_count * BATCH_PER_CONTEXT):
            cycle = needs_fix[cycle_start:cycle_start + ctx_count * BATCH_PER_CONTEXT]

            chunks = []
            for ci in range(ctx_count):
                chunk = cycle[ci * BATCH_PER_CONTEXT:(ci + 1) * BATCH_PER_CONTEXT]
                if chunk:
                    chunks.append(chunk)

            tasks = [
                _title_worker(browser, ci + 1, chunk, products,
                              session_path if not use_proxy else None,
                              progress)
                for ci, chunk in enumerate(chunks)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            cycle_fixed = sum(r for r in results if isinstance(r, int))
            fixed_total = progress["fixed"]
            titles_since_restart += cycle_fixed

            # Save checkpoint every cycle
            checkpoint_path = Path("scrape_checkpoint.json")
            data = json.loads(checkpoint_path.read_text())
            data["products"] = products
            checkpoint_path.write_text(json.dumps(data, ensure_ascii=False))

            elapsed = time.time() - start_time
            rate = progress["done"] / max(elapsed, 1) * 60
            remaining = len(needs_fix) - cycle_start - len(cycle)
            eta = remaining / max(rate, 1) if rate > 0 else 0
            print(f"  [{cycle_start + len(cycle)}/{len(needs_fix)}] "
                  f"{fixed_total} fixed | {rate:.0f}/min | ETA: {eta:.0f} min")

            # Browser restart
            if titles_since_restart >= BROWSER_RESTART and remaining > 0:
                await browser.close()
                await asyncio.sleep(2)
                browser = await pw.chromium.launch(**launch_args)
                titles_since_restart = 0
                print(f"  Browser restarted")

        await browser.close()

    return fixed_total


async def _title_worker(browser, worker_id, items, products, session_path,
                         progress):
    """One context that extracts h1 titles from a list of (index, url) pairs."""
    import random
    from scraper import STEALTH_JS, USER_AGENTS

    ua = random.choice(USER_AGENTS)
    vp = {"width": random.choice([1280, 1366, 1440, 1920]),
          "height": random.choice([720, 900, 1080])}

    ctx_kwargs = dict(user_agent=ua, viewport=vp, locale="en-US")
    if session_path:
        ctx_kwargs["storage_state"] = session_path

    context = await browser.new_context(**ctx_kwargs)
    fixed = 0

    for idx, url in items:
        try:
            page = await context.new_page()
            await page.add_init_script(STEALTH_JS)
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)

            # Give JS 3 seconds to render the title
            await page.wait_for_timeout(3000)

            title = ""

            # 1. Try h1 selectors
            for sel in ['h1[data-pl="product-title"]', "h1.product-title-text",
                         "h1", '[class*="title--wrap"] h1']:
                el = await page.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if len(text) > 5 and "aliexpress" not in text.lower()[:15]:
                        title = text
                        break

            # 2. og:title via JS evaluate (works even if DOM not fully ready)
            if not title:
                try:
                    og_text = await page.evaluate(
                        'document.querySelector("meta[property=\'og:title\']")?.content || ""'
                    )
                    og_text = og_text.strip() if og_text else ""
                    if og_text and len(og_text) > 5 and "aliexpress" not in og_text.lower()[:15]:
                        title = og_text
                except Exception:
                    pass

            # 3. Browser tab title (strip " - AliExpress" suffix)
            if not title:
                page_title = (await page.title()).strip()
                page_title = re.sub(r"\s*[-|]\s*AliExpress.*$", "", page_title,
                                     flags=re.IGNORECASE)
                if page_title and len(page_title) > 5 and "aliexpress" not in page_title.lower():
                    title = page_title

            # Validate: reject captcha pages, junk, and too-short titles
            junk_phrases = ["captcha", "interception", "access denied",
                             "please verify", "just a moment", "security check",
                             "robot check", "404", "not found", "page not found"]
            if title and any(j in title.lower() for j in junk_phrases):
                title = ""  # reject
            if title and len(title) < 10:
                title = ""  # too short to be a real title
            if title and "aliexpress" in title.lower():
                title = ""  # still has aliexpress in it

            # Strip " - AliExpress 26" suffix
            if title:
                title = re.sub(r"\s*-\s*AliExpress\s*\d*\s*$", "", title,
                               flags=re.IGNORECASE).strip()

            if title:
                products[idx]["product_title"] = title
                fixed += 1
                progress["fixed"] += 1

                if progress["fixed"] == 1:
                    print(f"  First title fixed: \"{title[:60]}\"")
            else:
                progress["failed"] += 1

            progress["done"] += 1
            # Print every 50
            if progress["done"] % 50 == 0:
                elapsed = time.time() - progress["start"]
                rate = progress["done"] / max(elapsed, 1) * 60
                print(f"  [{progress['done']}/{progress['total']}] "
                      f"Fixed {progress['fixed']}, Failed {progress['failed']} "
                      f"— {rate:.0f}/min")

            await page.close()

        except Exception:
            progress["done"] += 1
            progress["failed"] += 1
            try:
                await page.close()
            except Exception:
                pass

    await context.close()
    return fixed
    """Apply branded overlays to products already on Shopify."""
    print("\n══════════════════════════════════════")
    print("  CastForge Brand Image Processor")
    print("══════════════════════════════════════\n")

    from uploader import get_shopify_token
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops

    BRAND_CACHE = Path("brand_image_cache.json")
    AMBER = (245, 158, 11)

    def _load_brand_cache():
        if BRAND_CACHE.exists():
            return json.loads(BRAND_CACHE.read_text())
        return {}

    def _save_brand_cache(cache):
        BRAND_CACHE.write_text(json.dumps(cache, indent=2))

    # Load upload log
    if not os.path.exists("upload_log.json"):
        print("  No upload_log.json found. Upload products first.")
        return

    with open("upload_log.json") as f:
        log = json.load(f)

    product_ids = log.get("product_ids", [])
    print(f"  Found {len(product_ids)} products in upload_log.json")

    token = get_shopify_token()
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base_url = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    cache = _load_brand_cache()
    processed = 0
    skipped = 0
    failed = 0

    for batch_start in range(0, len(product_ids), 10):
        batch = product_ids[batch_start:batch_start + 10]

        for pid in batch:
            pid_str = str(pid)
            if pid_str in cache:
                skipped += 1
                continue

            try:
                # Fetch product
                resp = requests.get(f"{base_url}/products/{pid}.json?fields=id,title,images",
                                     headers=headers)
                if resp.status_code != 200:
                    failed += 1
                    continue

                product = resp.json()["product"]
                title = product.get("title", "")
                product_images = product.get("images", [])
                if not product_images:
                    failed += 1
                    continue

                first_image = product_images[0]
                img_url = first_image.get("src", "")
                if not img_url:
                    failed += 1
                    continue

                # Download image
                img_resp = requests.get(img_url, timeout=15)
                if img_resp.status_code != 200:
                    failed += 1
                    continue

                original = Image.open(io.BytesIO(img_resp.content)).convert("RGB")

                # Apply branded overlay
                canvas = original.copy()
                w, h = canvas.size

                # Dark vignette
                vignette = Image.new("L", (w, h), 0)
                draw_v = ImageDraw.Draw(vignette)
                cx, cy = w // 2, h // 2
                max_r = int((w ** 2 + h ** 2) ** 0.5 / 2)
                for r in range(max_r, 0, -4):
                    brightness = int(100 * (r / max_r) ** 2)
                    draw_v.ellipse([cx - r, cy - r, cx + r, cy + r], fill=brightness)
                vignette = vignette.filter(ImageFilter.GaussianBlur(60))
                vignette_rgb = Image.merge("RGB", [vignette, vignette, vignette])
                canvas = ImageChops.subtract(canvas, vignette_rgb)

                # Watermark
                overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                draw_w = ImageDraw.Draw(overlay)
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
                except (OSError, IOError):
                    try:
                        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 18)
                    except (OSError, IOError):
                        font = ImageFont.load_default()
                bbox = draw_w.textbbox((0, 0), "CASTFORGE", font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                draw_w.text((w - tw - 30, h - th - 25), "CASTFORGE",
                            fill=(*AMBER, 26), font=font)
                canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")

                # Scale badge
                scale = ""
                m = re.search(r"(\d{2,3})\s*mm", title, re.IGNORECASE)
                if m:
                    scale = f"{m.group(1)}mm"
                else:
                    m = re.search(r"1[:/](\d{1,3})", title)
                    if m:
                        scale = f"1/{m.group(1)}"

                if scale:
                    badge_overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                    draw_b = ImageDraw.Draw(badge_overlay)
                    try:
                        bfont = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
                    except (OSError, IOError):
                        try:
                            bfont = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
                        except (OSError, IOError):
                            bfont = ImageFont.load_default()
                    bbox = draw_b.textbbox((0, 0), scale, font=bfont)
                    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                    px, py = 12, 6
                    bx, by = 25, h - th - py * 2 - 25
                    draw_b.rounded_rectangle([bx, by, bx + tw + px * 2, by + th + py * 2],
                                              radius=8, fill=(20, 20, 20, 200))
                    draw_b.text((bx + px, by + py), scale, fill=(*AMBER, 230), font=bfont)
                    canvas = Image.alpha_composite(canvas.convert("RGBA"), badge_overlay).convert("RGB")

                # Save to buffer
                buf = io.BytesIO()
                canvas.save(buf, "JPEG", quality=92)
                img_b64 = base64.b64encode(buf.getvalue()).decode()

                # Upload as new position 1 image
                upload_resp = requests.post(
                    f"{base_url}/products/{pid}/images.json",
                    headers=headers,
                    json={"image": {
                        "attachment": img_b64,
                        "filename": f"castforge_hero_{pid}.jpg",
                        "position": 1,
                    }},
                )
                if upload_resp.status_code == 200:
                    cache[pid_str] = True
                    processed += 1
                else:
                    failed += 1

                time.sleep(0.5)

            except Exception as e:
                failed += 1
                if failed <= 3:
                    print(f"    Error: {str(e)[:80]}")

        _save_brand_cache(cache)
        done = batch_start + len(batch)
        print(f"  [{done}/{len(product_ids)}] {processed} branded, "
              f"{skipped} cached, {failed} failed")

    print(f"\n  Done: {processed} branded, {skipped} already done, {failed} failed")


def cmd_review():
    """Print needs_review.csv grouped by suggested category."""
    review_path = Path("needs_review.csv")
    if not review_path.exists():
        print("No needs_review.csv found. Run export first.")
        return

    print("\n══════════════════════════════════════")
    print("  CastForge Review Queue")
    print("══════════════════════════════════════\n")

    import csv as csv_mod
    with open(review_path, newline="", encoding="utf-8") as f:
        reader = csv_mod.DictReader(f)
        items = list(reader)

    if not items:
        print("  Review queue is empty.")
        return

    # Group by suggested category
    groups = {}
    for item in items:
        cat = item.get("suggested", "unknown")
        if cat not in groups:
            groups[cat] = []
        groups[cat].append(item)

    print(f"  Total: {len(items)} products need review\n")

    for cat in sorted(groups, key=lambda c: -len(groups[c])):
        cat_items = groups[cat]
        display = categorizer.CATEGORY_DISPLAY_NAMES.get(cat, cat)
        print(f"  ── {display} ({len(cat_items)}) ──")
        for item in cat_items[:30]:
            title = item.get("title", "")[:70]
            reason = item.get("reason", "")
            print(f"    {title}")
            if reason:
                print(f"      → {reason}")
        if len(cat_items) > 30:
            print(f"    ... and {len(cat_items) - 30} more")
        print()


ALI_COOKIES_FILE = Path("ali_cookies.json")


def _capture_ali_login():
    """Open visible browser for user to log in, save cookies."""
    from playwright.sync_api import sync_playwright

    print("  Opening browser for AliExpress login...")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="en-GB",
        )
        page = context.new_page()
        page.goto("https://www.aliexpress.com/", wait_until="domcontentloaded")

        input("\n  Please log in to AliExpress. Press Enter when done... ")

        cookies = context.cookies()
        ALI_COOKIES_FILE.write_text(json.dumps(cookies, indent=2))
        print(f"  Saved {len(cookies)} cookies to {ALI_COOKIES_FILE}")

        context.close()
        browser.close()


def _load_ali_cookies():
    """Load cookies from ali_cookies.json and convert to requests dict format."""
    if not ALI_COOKIES_FILE.exists():
        return {}
    cookies_list = json.loads(ALI_COOKIES_FILE.read_text())
    return {c["name"]: c["value"] for c in cookies_list}


def cmd_fix_scrape_prices(relogin=False):
    """Re-scrape prices with login cookies + proxy. 60 threads."""
    from concurrent.futures import ThreadPoolExecutor
    import threading

    PROXY = "http://jpo1c9lb5mytbj0t:GnXsjzZq15h0WEdY@geo.iproyal.com:12321"
    WORKERS = 60
    SAVE_EVERY = 500

    print("\n══════════════════════════════════════")
    print("  CastForge Price Re-Scraper")
    print("══════════════════════════════════════\n")

    # Step 1: Login if needed
    if relogin or not ALI_COOKIES_FILE.exists():
        _capture_ali_login()

    cookies = _load_ali_cookies()
    if not cookies:
        print("  No cookies found. Run with --relogin.")
        return

    print(f"  Loaded {len(cookies)} cookies from {ALI_COOKIES_FILE}")

    cp_path = Path("scrape_checkpoint.json")
    if not cp_path.exists():
        print("  No scrape_checkpoint.json found.")
        return

    data = json.loads(cp_path.read_text())
    products = data.get("products", [])

    needs_price = []
    for i, p in enumerate(products):
        price = p.get("product_price", "")
        if not price or _parse_price(price) <= 0:
            url = p.get("product_url") or p.get("source_url", "")
            if url:
                needs_price.append((i, url))

    print(f"  Total products: {len(products)}")
    print(f"  Missing prices: {len(needs_price)}")
    print(f"  Workers: {WORKERS} (proxy + cookies)")

    if not needs_price:
        print("  All products have prices!")
        return

    print(f"  Estimated: {len(needs_price) / (WORKERS * 4):.0f} minutes\n")

    lock = threading.Lock()
    progress = {"done": 0, "found": 0, "failed": 0, "start": time.time()}

    def _scrape_price(item):
        idx, url = item
        proxies = {"http": PROXY, "https": PROXY}
        headers_req = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-GB,en;q=0.9",
        }

        price = ""
        shipping = ""

        for attempt in range(2):
            try:
                resp = requests.get(url, headers=headers_req, proxies=proxies,
                                     cookies=cookies, timeout=15,
                                     allow_redirects=True)
                if resp.status_code not in (200, 206):
                    continue

                text = resp.text

                # 1. og:title — often has price
                m = re.search(r'og:title["\s]+content="([^"]+)"', text)
                if m:
                    pm = re.search(r'[\uffe1\xa3]([\d.]+)', m.group(1))
                    if pm:
                        price = f"\u00a3{pm.group(1)}"

                # 2. minPrice / formatedAmount in JSON
                if not price:
                    for pattern in [
                        r'"minPrice"\s*:\s*"?([\d.]+)"?',
                        r'"formatedAmount"\s*:\s*"[\uffe1\xa3]?([\d.]+)"',
                        r'"activityPrice"\s*:\s*\{[^}]*"minPrice"\s*:\s*"?([\d.]+)"?',
                        r'"discountPrice"\s*:\s*\{[^}]*"minPrice"\s*:\s*"?([\d.]+)"?',
                    ]:
                        m = re.search(pattern, text)
                        if m:
                            price = f"\u00a3{m.group(1)}"
                            break

                # 3. Raw regex for ￡X.XX or £X.XX
                if not price:
                    m = re.search(r'[\uffe1\xa3]\s*(\d+\.\d{2})', text)
                    if m:
                        price = f"\u00a3{m.group(1)}"

                # Shipping
                sm = re.search(r'"freightAmount"\s*:\s*\{[^}]*"value"\s*:\s*"?([\d.]+)"?', text)
                if not sm:
                    sm = re.search(r'"shippingFee"\s*:\s*"?([\d.]+)"?', text)
                if sm:
                    val = float(sm.group(1))
                    shipping = str(val) if val > 0 else "0"
                elif re.search(r'free\s+shipping', text, re.IGNORECASE):
                    if not re.search(r'free shipping over|free shipping on orders', text, re.IGNORECASE):
                        shipping = "0"

                if price:
                    break

            except Exception:
                if attempt == 0:
                    time.sleep(1)
                continue

        with lock:
            progress["done"] += 1
            if price:
                products[idx]["product_price"] = price
                if shipping:
                    products[idx]["shipping"] = shipping
                progress["found"] += 1
            else:
                progress["failed"] += 1

            done = progress["done"]
            if done % 100 == 0 or done == len(needs_price):
                elapsed = time.time() - progress["start"]
                rate = done / max(elapsed, 1) * 60
                eta = (len(needs_price) - done) / max(rate, 1)
                print(f"  [{done}/{len(needs_price)}] "
                      f"Found {progress['found']}, Failed {progress['failed']} "
                      f"| {rate:.0f}/min | ETA: {eta:.0f} min")

            if done % SAVE_EVERY == 0:
                data["products"] = products
                cp_path.write_text(json.dumps(data, ensure_ascii=False))

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        list(executor.map(_scrape_price, needs_price))

    # Final save
    data["products"] = products
    cp_path.write_text(json.dumps(data, ensure_ascii=False))

    print(f"\n  Done: {progress['found']} prices found, {progress['failed']} failed")
    print(f"  Checkpoint saved")

    # Regenerate all_products.csv
    print(f"\n  Regenerating all_products.csv...")
    import csv as csv_mod
    fieldnames = [
        "id", "product_title", "product_price", "product_original_price",
        "product_discount", "product_url", "product_image", "product_images",
        "product_rating", "store_name", "store_url", "store_id",
        "total_sales", "ship_from", "store_member_id", "trade_info",
        "shipping", "launch_time", "company_name", "source_url",
        "variations", "variation_images",
    ]
    with open("all_products.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv_mod.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for p in products:
            writer.writerow(p)
    print(f"  Saved all_products.csv ({len(products)} products)")


def cmd_dedup_shopify():
    """Deduplicate Shopify products by title. Keep lowest ID, delete dupes."""
    from uploader import get_shopify_token
    from concurrent.futures import ThreadPoolExecutor

    print("\n══════════════════════════════════════")
    print("  CastForge Shopify Deduplicator")
    print("══════════════════════════════════════\n")

    token = get_shopify_token()
    headers = {"X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    # Fetch ALL products
    products = []
    url = f"{base}/products.json?limit=250&fields=id,title"
    while url:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 2)))
            continue
        products.extend(r.json().get("products", []))
        link = r.headers.get("Link", "")
        url = None
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.split("<")[1].split(">")[0]

    print(f"  Found {len(products)} total products")

    # Group by title
    by_title = {}
    for p in products:
        title = p["title"]
        if title not in by_title:
            by_title[title] = []
        by_title[title].append(p["id"])

    # Find dupes (keep lowest ID)
    to_delete = []
    for title, ids in by_title.items():
        if len(ids) > 1:
            ids.sort()
            to_delete.extend(ids[1:])  # keep first (lowest), delete rest

    print(f"  Duplicates to delete: {len(to_delete)}")
    if not to_delete:
        print("  No duplicates found!")
        return

    deleted = [0]
    lock = __import__("threading").Lock()

    def _delete_one(pid):
        while True:
            r = requests.delete(f"{base}/products/{pid}.json",
                                headers=headers, timeout=30)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 2)))
                continue
            break
        with lock:
            deleted[0] += 1
            if deleted[0] % 50 == 0 or deleted[0] == len(to_delete):
                print(f"    [{deleted[0]}/{len(to_delete)}] deleted")
        time.sleep(0.3)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(_delete_one, to_delete))

    print(f"  Done: {deleted[0]} duplicates deleted")


def cmd_fix_prices_fast(csv_path=None):
    """Fast price fix using 2 threads. Matches via source URL tag."""
    from uploader import get_shopify_token
    from concurrent.futures import ThreadPoolExecutor
    import threading

    print("\n══════════════════════════════════════")
    print("  CastForge Price Fixer (2 threads)")
    print("══════════════════════════════════════\n")

    # Build price lookup from source data
    source_products = []
    if csv_path:
        print(f"  Loading prices from {csv_path}")
        import csv as csv_mod
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv_mod.DictReader(f):
                source_products.append(dict(row))
    else:
        cp = Path("scrape_checkpoint.json")
        if cp.exists():
            print("  Loading prices from scrape_checkpoint.json")
            data = json.loads(cp.read_text())
            source_products = data.get("products", [])
        else:
            print("  No source data. Usage: python3 main.py fix-prices <source.csv>")
            return

    price_lookup = {}
    for sp in source_products:
        url = sp.get("product_url") or sp.get("source_url", "")
        if url:
            price_lookup[url] = (
                _parse_price(sp.get("product_price", "")),
                _parse_price(sp.get("shipping", "0")),
            )

    has_price = sum(1 for p, s in price_lookup.values() if p > 0)
    print(f"  Source products: {len(price_lookup)} ({has_price} with actual prices)\n")

    # Fetch all Shopify products
    token = get_shopify_token()
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    products = []
    url = f"{base}/products.json?limit=250&fields=id,title,tags,variants"
    while url:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 2)))
            continue
        products.extend(r.json().get("products", []))
        link = r.headers.get("Link", "")
        url = None
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.split("<")[1].split(">")[0]

    print(f"  Shopify products: {len(products)}")

    # Build update queue
    updates = []
    for prod in products:
        source_url = ""
        for tag in (prod.get("tags", "") or "").split(","):
            tag = tag.strip()
            if tag.startswith("source:"):
                source_url = tag[7:]
                break

        if not source_url or source_url not in price_lookup:
            continue

        price_gbp, ship_gbp = price_lookup[source_url]
        if price_gbp <= 0:
            continue

        sell_usd, compare_usd = calculate_price(price_gbp, ship_gbp)
        variant = prod.get("variants", [{}])[0]
        variant_id = variant.get("id")
        current_price = float(variant.get("price", "0"))

        if variant_id and abs(current_price - sell_usd) > 0.01:
            updates.append((variant_id, sell_usd, compare_usd, prod["title"][:40]))

    print(f"  Products to update: {len(updates)}\n")
    if not updates:
        print("  Nothing to update!")
        return

    updated = [0]
    failed = [0]
    lock = threading.Lock()

    def _update_one(item):
        vid, price, compare, title = item
        try:
            r = requests.put(
                f"{base}/variants/{vid}.json",
                headers=headers, timeout=30,
                json={"variant": {"id": vid, "price": f"{price:.2f}",
                                   "compare_at_price": f"{compare:.2f}"}},
            )
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 2)))
                r = requests.put(
                    f"{base}/variants/{vid}.json",
                    headers=headers, timeout=30,
                    json={"variant": {"id": vid, "price": f"{price:.2f}",
                                       "compare_at_price": f"{compare:.2f}"}},
                )
            with lock:
                if r.status_code == 200:
                    updated[0] += 1
                else:
                    failed[0] += 1
                done = updated[0] + failed[0]
                if done % 50 == 0 or done == len(updates):
                    print(f"    [{done}/{len(updates)}] {updated[0]} OK, {failed[0]} failed")
        except Exception:
            with lock:
                failed[0] += 1
        time.sleep(0.25)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(_update_one, updates))

    print(f"\n  Done: {updated[0]} prices updated, {failed[0]} failed")


def cmd_upload_failed():
    """Upload products from failed_uploads.csv."""
    failed_path = Path("failed_uploads.csv")
    if not failed_path.exists():
        print("No failed_uploads.csv found.")
        return

    print("\n══════════════════════════════════════")
    print("  CastForge Failed Upload Retry")
    print("══════════════════════════════════════\n")

    # Load failed products — these need to be re-processed from source
    import csv as csv_mod
    failed_titles = set()
    with open(failed_path, newline="", encoding="utf-8") as f:
        for row in csv_mod.DictReader(f):
            failed_titles.add(row.get("title", "")[:80])

    print(f"  Failed products to retry: {len(failed_titles)}")
    print("  To retry: re-run the upload command. Failed products will be")
    print("  re-attempted since they're not in upload_progress.json.")
    print("  Usage: python3 main.py upload all_products.csv --resume")


def cmd_fix_images():
    """Two-pass image fixer for existing Shopify products."""
    from uploader import get_shopify_token
    token = get_shopify_token()
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    print("\n══════════════════════════════════════")
    print("  CastForge Image Fixer")
    print("══════════════════════════════════════\n")

    api_key = config.ANTHROPIC_API_KEY
    if not api_key or api_key == "sk-ant-xxx":
        print("  ANTHROPIC_API_KEY required for image scanning.")
        return

    # Fetch all products
    products = []
    url = f"{base}/products.json?limit=250&fields=id,title,images,tags"
    while url:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 2)))
            continue
        products.extend(r.json().get("products", []))
        link = r.headers.get("Link", "")
        url = None
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.split("<")[1].split(">")[0]

    print(f"  Found {len(products)} products\n")

    # ── Pass 1: Remove junk hero images ──
    print("  ── Pass 1: Remove junk hero images ──")
    junk_removed = 0
    for i, prod in enumerate(products):
        imgs = prod.get("images", [])
        if not imgs:
            continue

        hero = imgs[0]
        hero_url = hero.get("src", "")
        if not hero_url:
            continue

        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                          "content-type": "application/json"},
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 10,
                    "messages": [{"role": "user", "content": [
                        {"type": "image", "source": {"type": "url", "url": hero_url}},
                        {"type": "text", "text": "Is this a real product photo of a resin miniature/model, OR a seller info graphic/text card/promotional banner/emoji? Reply ONLY: PRODUCT or JUNK"},
                    ]}],
                },
                timeout=20,
            )
            if resp.status_code == 200:
                answer = resp.json()["content"][0]["text"].strip().upper()
                if "JUNK" in answer:
                    # Delete the junk image
                    requests.delete(f"{base}/products/{prod['id']}/images/{hero['id']}.json",
                                     headers=headers, timeout=15)
                    junk_removed += 1
                    time.sleep(0.3)
        except Exception:
            pass

        if (i + 1) % 50 == 0:
            print(f"    [{i+1}/{len(products)}] Removed {junk_removed} junk images")

    print(f"  Pass 1 done: {junk_removed} junk images removed\n")

    # ── Pass 2: Flag mismatched images ──
    print("  ── Pass 2: Flag image mismatches ──")
    mismatches = []
    for i, prod in enumerate(products):
        imgs = prod.get("images", [])
        if not imgs:
            continue
        hero_url = imgs[0].get("src", "")
        title = prod.get("title", "")
        if not hero_url or not title:
            continue

        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                          "content-type": "application/json"},
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 30,
                    "messages": [{"role": "user", "content": [
                        {"type": "image", "source": {"type": "url", "url": hero_url}},
                        {"type": "text", "text": f"Does this image match this product? Title: {title}. Reply YES or NO with brief reason."},
                    ]}],
                },
                timeout=20,
            )
            if resp.status_code == 200:
                answer = resp.json()["content"][0]["text"].strip()
                if answer.upper().startswith("NO"):
                    mismatches.append({"id": prod["id"], "title": title,
                                        "image": hero_url, "reason": answer})
        except Exception:
            pass

        if (i + 1) % 50 == 0:
            print(f"    [{i+1}/{len(products)}] {len(mismatches)} mismatches found")

    if mismatches:
        import csv as csv_mod
        with open("image_mismatches.csv", "w", newline="", encoding="utf-8") as f:
            w = csv_mod.DictWriter(f, fieldnames=["id", "title", "image", "reason"])
            w.writeheader()
            w.writerows(mismatches)
        print(f"  Pass 2 done: {len(mismatches)} mismatches → image_mismatches.csv")
    else:
        print(f"  Pass 2 done: no mismatches found")


def cmd_fix_shopify_titles():
    """Fix garbage titles on existing Shopify products via AI."""
    from uploader import get_shopify_token
    token = get_shopify_token()
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    print("\n══════════════════════════════════════")
    print("  CastForge Shopify Title Fixer")
    print("══════════════════════════════════════\n")

    api_key = config.ANTHROPIC_API_KEY
    if not api_key or api_key == "sk-ant-xxx":
        print("  ANTHROPIC_API_KEY required.")
        return

    # Fetch all products
    products = []
    url = f"{base}/products.json?limit=250&fields=id,title,tags"
    while url:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 2)))
            continue
        products.extend(r.json().get("products", []))
        link = r.headers.get("Link", "")
        url = None
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.split("<")[1].split(">")[0]

    # Find garbage titles
    garbage = []
    for p in products:
        title = p.get("title", "")
        if ("，" in title or title.startswith("And ") or len(title) < 15 or
                "SKIP" in title or title.startswith(": ")):
            # Extract source URL from tags
            raw_title = ""
            for tag in (p.get("tags", "") or "").split(","):
                tag = tag.strip()
                if tag.startswith("source:"):
                    raw_title = tag[7:]
                    break
            garbage.append({"id": p["id"], "title": title, "raw": raw_title})

    print(f"  Found {len(garbage)} products with garbage titles")
    if not garbage:
        return

    fixed = 0
    for i, g in enumerate(garbage):
        raw = g["raw"] or g["title"]
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                          "content-type": "application/json"},
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 80,
                    "messages": [{"role": "user", "content":
                        f"Write a product title for a resin miniature store. "
                        f"Format: [Subject] [Scale] Resin [Figure/Bust]. Max 80 chars. "
                        f"Raw title: {raw[:150]}. Write ONLY the title:"}],
                },
                timeout=15,
            )
            if resp.status_code == 200:
                new_title = resp.json()["content"][0]["text"].strip().strip('"\'')
                if new_title and len(new_title) > 10 and new_title.upper() != "SKIP":
                    requests.put(f"{base}/products/{g['id']}.json",
                                  headers=headers, timeout=15,
                                  json={"product": {"id": g["id"], "title": new_title}})
                    fixed += 1
        except Exception:
            pass

        if (i + 1) % 20 == 0:
            print(f"    [{i+1}/{len(garbage)}] Fixed {fixed}")

    print(f"  Done: {fixed} titles fixed")


def cmd_fix_prices(csv_path=None):
    """Recalculate prices from CSV source data and update Shopify products."""
    from uploader import get_shopify_token

    print("\n══════════════════════════════════════")
    print("  CastForge Price Fixer")
    print("══════════════════════════════════════\n")

    if not csv_path:
        # Try checkpoint
        cp = Path("scrape_checkpoint.json")
        if cp.exists():
            print("  Using scrape_checkpoint.json as price source")
            data = json.loads(cp.read_text())
            source_products = data.get("products", [])
        else:
            print("  No CSV or checkpoint found. Usage: python3 main.py fix-prices <source.csv>")
            return
    else:
        print(f"  Using {csv_path} as price source")
        source_products = []
        import csv as csv_mod
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv_mod.DictReader(f)
            for row in reader:
                source_products.append(dict(row))

    # Build price lookup: source_url → (price_gbp, shipping_gbp)
    price_lookup = {}
    for sp in source_products:
        url = sp.get("product_url") or sp.get("source_url", "")
        price_raw = sp.get("product_price", "")
        ship_raw = sp.get("shipping", "0")
        if url:
            price_gbp = _parse_price(price_raw)
            ship_gbp = _parse_price(ship_raw)
            price_lookup[url] = (price_gbp, ship_gbp)

    print(f"  Price lookup: {len(price_lookup)} products with source URLs")
    prices_with_data = sum(1 for p, s in price_lookup.values() if p > 0)
    print(f"  Products with actual prices: {prices_with_data}")
    print(f"  Products with price=0 (scraper missed): {len(price_lookup) - prices_with_data}")

    if prices_with_data == 0:
        print("\n  No actual prices found in source data. Scraper needs to re-capture prices.")
        print("  To fix: re-scrape URLs with --debug to check price extraction.")
        return

    # Fetch all Shopify products
    token = get_shopify_token()
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    products = []
    url = f"{base}/products.json?limit=250&fields=id,title,tags,variants"
    while url:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 2)))
            continue
        products.extend(r.json().get("products", []))
        link = r.headers.get("Link", "")
        url = None
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.split("<")[1].split(">")[0]

    print(f"  Shopify products: {len(products)}")

    # Match and update
    updated = 0
    skipped = 0
    no_match = 0

    for i, prod in enumerate(products):
        # Extract source URL from tags
        source_url = ""
        for tag in (prod.get("tags", "") or "").split(","):
            tag = tag.strip()
            if tag.startswith("source:"):
                source_url = tag[7:]
                break

        if not source_url or source_url not in price_lookup:
            no_match += 1
            continue

        price_gbp, ship_gbp = price_lookup[source_url]
        if price_gbp <= 0:
            skipped += 1
            continue

        sell_usd, compare_usd = calculate_price(price_gbp, ship_gbp)

        # Check if price actually changed
        variant = prod.get("variants", [{}])[0]
        current_price = float(variant.get("price", "0"))
        if abs(current_price - sell_usd) < 0.01:
            skipped += 1
            continue

        # Update
        variant_id = variant.get("id")
        if variant_id:
            try:
                r = requests.put(
                    f"{base}/variants/{variant_id}.json",
                    headers=headers, timeout=30,
                    json={"variant": {
                        "id": variant_id,
                        "price": f"{sell_usd:.2f}",
                        "compare_at_price": f"{compare_usd:.2f}",
                    }},
                )
                if r.status_code == 200:
                    updated += 1
                time.sleep(0.3)
            except Exception:
                pass

        if (i + 1) % 100 == 0:
            print(f"    [{i+1}/{len(products)}] {updated} updated, {skipped} skipped")

    print(f"\n  Done: {updated} prices updated, {skipped} skipped, {no_match} no source match")


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

USAGE = """
CastForge Pipeline CLI

Usage:
  python main.py comply <input.csv>              Title compliance scan
  python main.py comply-images <input.csv>       Image compliance scan (Claude Vision)
  python main.py upload <input.csv>              Full pipeline: comply → categorize → upload
  python main.py export <input.csv> [--fast]     Comply → categorize → Shopify CSV export
  python main.py process-images <input.csv>      Download + process images (rembg)
  python main.py stats <input.csv>               Category breakdown (no upload)
  python main.py scrape <urls.txt>               Scrape AliExpress URLs to CSV
  python main.py audit                           Audit existing Shopify products
  streamlit run dashboard.py                     Web dashboard UI

Flags:
  --fast    Skip image processing (use original images as-is)
"""

COMMANDS_WITH_FILE = ("comply", "comply-images", "upload", "export", "process-images", "stats", "scrape")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(1)

    command = sys.argv[1]
    args = sys.argv[2:]
    fast_mode = "--fast" in args
    debug_mode = "--debug" in args
    file_args = [a for a in args if not a.startswith("--")]

    # Parse --limit N and --speed fast|safe
    limit_val = None
    speed_val = "safe"
    for i, a in enumerate(args):
        if a == "--limit" and i + 1 < len(args):
            try:
                limit_val = int(args[i + 1])
            except ValueError:
                pass
        if a == "--speed" and i + 1 < len(args):
            speed_val = args[i + 1]

    if command in COMMANDS_WITH_FILE and not file_args:
        print(f"Error: {command} requires an input file")
        print(USAGE)
        sys.exit(1)

    if command == "comply":
        cmd_comply(file_args[0])
    elif command == "comply-images":
        cmd_comply_images(file_args[0])
    elif command == "upload":
        resume_mode = "--resume" in args
        cmd_upload(file_args[0], resume=resume_mode)
    elif command == "export":
        cmd_export(file_args[0], fast=fast_mode)
    elif command == "process-images":
        cmd_process_images(file_args[0], fast=fast_mode)
    elif command == "stats":
        cmd_stats(file_args[0])
    elif command == "scrape":
        cmd_scrape(file_args[0], limit=limit_val, debug=debug_mode, speed=speed_val)
    elif command == "audit":
        cmd_audit()
    elif command == "brand-images":
        cmd_brand_images()
    elif command == "fix-titles":
        proxy_mode = "--proxy" in args
        cmd_fix_titles(use_proxy=proxy_mode)
    elif command == "review":
        cmd_review()
    elif command == "nuke":
        cmd_nuke()
    elif command == "fix-images":
        cmd_fix_images()
    elif command == "fix-shopify-titles":
        cmd_fix_shopify_titles()
    elif command == "fix-prices":
        cmd_fix_prices_fast(file_args[0] if file_args else None)
    elif command == "dedup-shopify":
        cmd_dedup_shopify()
    elif command == "fix-scrape-prices":
        cmd_fix_scrape_prices(relogin="--relogin" in args)
    elif command == "upload-failed":
        cmd_upload_failed()
    else:
        print(f"Unknown command: {command}")
        print(USAGE)
        sys.exit(1)
