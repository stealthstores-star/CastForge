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

import csv
import hashlib
import json
import math
import sys
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
            product = {
                "title": row.get(col_title, "").strip(),
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

    print(f"  Loaded {len(products)} products from {path}\n")
    return products


# ═══════════════════════════════════════════════════════════════
# PRICING
# ═══════════════════════════════════════════════════════════════

def _parse_price(raw):
    """Parse a price string like '£3.12' or '3.12' into float."""
    if not raw:
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", str(raw))
    try:
        return float(cleaned)
    except ValueError:
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
        raw_title = p["title"]
        handle, score, parent = categorizer.categorize(raw_title)
        scale = categorizer.detect_scale(raw_title)

        price_gbp = _parse_price(p.get("raw_price", "0"))
        shipping_gbp = _parse_price(p.get("raw_shipping", "0"))
        sell_usd, compare_usd = calculate_price(price_gbp, shipping_gbp)

        image_url = p.get("image_url", "")
        images_raw = p.get("images", "")
        if images_raw:
            first_full = images_raw.split("|")[0].strip()
            if first_full:
                image_url = first_full

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

    # AI categorization pass for low-scoring products
    api_key = config.ANTHROPIC_API_KEY
    if needs_ai and api_key and api_key != "sk-ant-xxx":
        categorizer.ai_categorize_batch(needs_ai, api_key)
    elif needs_ai:
        print(f"  {len(needs_ai)} products need AI categorization but no ANTHROPIC_API_KEY set")
        print(f"  Using fallback: Props & Accessories")

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
        product_data.pop("_score", None)

    # Category breakdown
    print(f"\n  {'Category':<35} {'Count':>5}")
    print(f"  {'-'*40}")
    for h in sorted(category_counts, key=category_counts.get, reverse=True):
        name = categorizer.CATEGORY_DISPLAY_NAMES.get(h, h)
        print(f"  {name:<35} {category_counts[h]:>5}")

    return export_products, blocked, dupes_removed


# ═══════════════════════════════════════════════════════════════
# IMAGE DOWNLOADER (AliExpress blocks hotlinking)
# ═══════════════════════════════════════════════════════════════

IMAGES_DIR = "downloaded_images"


def download_product_images(products):
    """
    Download all product images locally. AliExpress blocks Shopify
    from loading images via hotlink, so we need local copies.
    Updates image_url and images fields to local paths.
    """
    os.makedirs(IMAGES_DIR, exist_ok=True)

    total_images = 0
    downloaded = 0
    skipped = 0
    failed = 0

    for pi, product in enumerate(products):
        # Download main image
        main_url = product.get("image_url", "")
        if main_url:
            local_path = _download_single_image(main_url, pi, 0)
            if local_path:
                product["image_url"] = local_path
                downloaded += 1
            else:
                failed += 1
            total_images += 1

        # Download additional images
        images_raw = product.get("images", "")
        if images_raw:
            urls = [u.strip() for u in images_raw.split("|") if u.strip()]
            local_paths = []
            for ii, url in enumerate(urls):
                local_path = _download_single_image(url, pi, ii + 1)
                if local_path:
                    local_paths.append(local_path)
                    downloaded += 1
                else:
                    failed += 1
                total_images += 1
            product["images"] = "|".join(local_paths)

        if (pi + 1) % 50 == 0 or (pi + 1) == len(products):
            print(f"  [{pi+1}/{len(products)}] {downloaded} downloaded, "
                  f"{failed} failed")

    print(f"  Images: {downloaded} downloaded, {failed} failed, "
          f"{skipped} skipped → {IMAGES_DIR}/")


def _download_single_image(url, product_idx, image_idx):
    """Download a single image, return local path or None."""
    if not url or not url.startswith("http"):
        return None

    # Generate stable filename from URL hash
    url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
    ext = ".jpg"
    if ".png" in url.lower():
        ext = ".png"
    elif ".jpeg" in url.lower():
        ext = ".jpeg"
    local_path = os.path.join(IMAGES_DIR, f"{product_idx:04d}_{image_idx}_{url_hash}{ext}")

    # Skip if already downloaded
    if os.path.exists(local_path):
        return local_path

    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.aliexpress.com/",
        })
        if resp.status_code == 200 and len(resp.content) > 1000:
            with open(local_path, "wb") as f:
                f.write(resp.content)
            return local_path
    except Exception:
        pass

    return None


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

    # Download images (AliExpress blocks hotlinking)
    if not fast:
        print(f"\nStep 3: Downloading images...")
        download_product_images(export_products)
    else:
        print(f"\n  --fast: skipping image download (Shopify may not load AliExpress URLs)")

    # Export
    output_path = csv_path.replace(".csv", "_shopify_import.csv")
    if output_path == csv_path:
        output_path = "shopify_import.csv"

    step = "4" if not fast else "3"
    print(f"\nStep {step}: Exporting Shopify CSV...")
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


def cmd_scrape(urls_file, limit=None):
    """Scrape AliExpress product URLs to CSV."""
    print("\n══════════════════════════════════════")
    print("  CastForge AliExpress Scraper")
    print("══════════════════════════════════════\n")

    from scraper import scrape_urls
    output = urls_file.replace(".txt", "_scraped.csv")
    if output == urls_file:
        output = "scraped_products.csv"
    scrape_urls(urls_file, output, limit=limit)


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
    file_args = [a for a in args if not a.startswith("--")]

    # Parse --limit N
    limit_val = None
    for i, a in enumerate(args):
        if a == "--limit" and i + 1 < len(args):
            try:
                limit_val = int(args[i + 1])
            except ValueError:
                pass

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
        cmd_scrape(file_args[0], limit=limit_val)
    elif command == "audit":
        cmd_audit()
    else:
        print(f"Unknown command: {command}")
        print(USAGE)
        sys.exit(1)
