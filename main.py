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

    # AI title generation for products with garbage cleaned titles
    if api_key and api_key != "sk-ant-xxx":
        categorizer.ai_generate_titles_batch(export_products, api_key)
        # Regenerate SEO for any products that got AI titles
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
    """Fix, filter, deduplicate, and order product images."""
    fixed = 0
    filtered = 0
    for product in products:
        # Collect all image URLs
        all_urls = []
        main = product.get("image_url", "")
        if main:
            all_urls.append(main)
        images_raw = product.get("images", "")
        if images_raw:
            for u in images_raw.split("|"):
                u = u.strip()
                if u and u not in all_urls:
                    all_urls.append(u)

        # Fix CDN URLs
        all_urls = [_fix_image_url(u) for u in all_urls]

        # Filter: only valid product images
        valid = [u for u in all_urls if _is_valid_product_image(u)]

        # Deduplicate by first 30 chars of /kf/ hash
        seen_hashes = set()
        deduped = []
        for u in valid:
            m = re.search(r"/kf/(S[^/.]{0,30})", u)
            h = m.group(1) if m else u[:50]
            if h not in seen_hashes:
                seen_hashes.add(h)
                deduped.append(u)

        # Keep original order — scraper already captured them correctly

        # Fallback: if all images filtered out, accept any alicdn .jpg
        if not deduped:
            fallback = [_fix_image_url(u) for u in all_urls
                        if "alicdn.com" in u and u.lower().endswith((".jpg", ".jpeg"))]
            if fallback:
                deduped = fallback[:6]

        # Apply
        if deduped:
            product["image_url"] = deduped[0]
            product["images"] = "|".join(deduped)
            fixed += 1
        else:
            product["image_url"] = ""
            product["images"] = ""
            filtered += 1

    print(f"  Images: {fixed} products with valid images, {filtered} with none")

    # Debug: show hero image for first 5 products
    print(f"  Hero images (first 5):")
    for p in products[:5]:
        img = p.get("image_url", "")
        title = p.get("title", p.get("_raw_title", ""))[:40]
        total = len(p.get("images", "").split("|")) if p.get("images") else 0
        print(f"    [{total} imgs] {title} → {img[-50:] if img else 'NONE'}")


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


def cmd_upload(csv_path):
    """Full pipeline: comply → dedup → categorize → price → upload as drafts."""
    print("\n╔══════════════════════════════════════╗")
    print("║  CastForge Full Upload Pipeline      ║")
    print("╚══════════════════════════════════════╝\n")

    print("Step 1: Loading CSV...")
    products = load_csv(csv_path)

    print("Step 2: Processing products...")
    upload_ready, blocked, dupes = process_products(products)

    if not upload_ready:
        print("\nNo products passed compliance. Aborting upload.")
        return

    # Price samples
    print(f"\n  Price samples (first 5):")
    for p in upload_ready[:5]:
        print(f"    ${p['price']:.2f} (was ${p['compare_at_price']:.2f}) — {p['title'][:50]}")

    # Upload
    print(f"\nStep 3: Uploading {len(upload_ready)} products to Shopify as drafts...")
    uploader = ShopifyUploader()
    results = uploader.upload_batch(upload_ready)
    uploader.print_summary()

    with open("upload_log.json", "w") as f:
        json.dump({
            "total": len(upload_ready),
            "success": results["success"],
            "failed": results["failed"],
            "product_ids": results["product_ids"],
            "blocked_count": len(blocked),
            "duplicates_removed": dupes,
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


def cmd_brand_images():
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
        cmd_upload(file_args[0])
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
    else:
        print(f"Unknown command: {command}")
        print(USAGE)
        sys.exit(1)
