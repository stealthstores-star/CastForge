#!/usr/bin/env python3
"""
CastForge Pipeline CLI

Commands:
  python main.py comply <input.csv>         — Run title compliance scan only
  python main.py comply-images <input.csv>  — Scan images via Claude Vision
  python main.py upload <input.csv>         — Full pipeline: comply → categorize → upload
  python main.py export <input.csv>         — Comply → categorize → Shopify CSV export
  python main.py stats <input.csv>          — Show category breakdown (no upload)
  python main.py scrape <urls.txt>          — Scrape AliExpress URLs to CSV
  python main.py audit                      — Audit existing Shopify products
"""

import csv
import json
import math
import sys
import os
import re

import requests

import config
import compliance
import categorizer
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
        clean_t = categorizer.clean_title(p["title"])
        handle, score, parent = categorizer.categorize(clean_t)
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
    """Full pipeline: comply → categorize → price → upload as drafts."""
    print("\n╔══════════════════════════════════════╗")
    print("║  CastForge Full Upload Pipeline      ║")
    print("╚══════════════════════════════════════╝\n")

    # ── Step 1: Load CSV ──
    print("Step 1: Loading CSV...")
    products = load_csv(csv_path)

    # ── Step 2: Compliance scan ──
    print("Step 2: Running compliance scan...")
    blocked, warnings, clean, changed = compliance.compliance_report(products)
    compliance.write_report(blocked, warnings, clean, changed)

    print(f"  Blocked:  {len(blocked)}")
    print(f"  Changed:  {len(changed)}")
    print(f"  Clean:    {len(clean)}")
    print(f"  Warnings: {len(warnings)}")

    # Merge clean + changed as uploadable (warnings go as drafts too in strict mode)
    uploadable = clean + changed
    if not uploadable:
        print("\nNo products passed compliance. Aborting upload.")
        return

    # ── Step 3: Categorize + Price + Enrich ──
    print(f"\nStep 3: Categorizing and pricing {len(uploadable)} products...")
    category_counts = {}
    upload_ready = []

    for p in uploadable:
        # Clean title (AliExpress junk)
        title = categorizer.clean_title(p["title"])

        # Categorize
        handle, score, parent = categorizer.categorize(title)
        category_counts[handle] = category_counts.get(handle, 0) + 1

        # Detect scale
        scale = categorizer.detect_scale(p["title"])

        # Calculate price
        price_gbp = _parse_price(p.get("raw_price", "0"))
        shipping_gbp = _parse_price(p.get("raw_shipping", "0"))
        sell_usd, compare_usd = calculate_price(price_gbp, shipping_gbp)

        # Generate description
        body_html = categorizer.generate_description(title, handle, scale)
        seo_title = categorizer.generate_seo_title(title)
        seo_desc = categorizer.generate_seo_description(title)

        # Get image URL (use full-size from product_images if available)
        image_url = p.get("image_url", "")
        images_raw = p.get("images", "")
        if images_raw:
            first_full = images_raw.split("|")[0].strip()
            if first_full:
                image_url = first_full

        # Parent display name for product_type
        parent_name = categorizer.PARENT_DISPLAY_NAMES.get(parent, "Collectible") if parent else "Collectible"

        upload_ready.append({
            "title": title,
            "body_html": body_html,
            "product_type": parent_name,
            "tags": "new",
            "price": sell_usd,
            "compare_at_price": compare_usd,
            "image_url": image_url,
            "category_handle": handle,
            "parent_handle": parent,
            "seo_title": seo_title,
            "seo_description": seo_desc,
        })

    # Print category breakdown
    print(f"\n  {'Category':<35} {'Count':>5}")
    print(f"  {'-'*40}")
    for handle in sorted(category_counts, key=category_counts.get, reverse=True):
        name = categorizer.CATEGORY_DISPLAY_NAMES.get(handle, handle)
        print(f"  {name:<35} {category_counts[handle]:>5}")

    # Print price samples
    print(f"\n  Price samples (first 5):")
    for p in upload_ready[:5]:
        print(f"    ${p['price']:.2f} (was ${p['compare_at_price']:.2f}) — {p['title'][:50]}")

    # ── Step 4: Upload to Shopify ──
    print(f"\nStep 4: Uploading {len(upload_ready)} products to Shopify as drafts...")
    uploader = ShopifyUploader()
    results = uploader.upload_batch(upload_ready)
    uploader.print_summary()

    # Save upload log
    with open("upload_log.json", "w") as f:
        json.dump({
            "total": len(upload_ready),
            "success": results["success"],
            "failed": results["failed"],
            "product_ids": results["product_ids"],
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


def cmd_export(csv_path):
    """Comply → categorize → price → export Shopify-compatible CSV."""
    print("\n╔══════════════════════════════════════╗")
    print("║  CastForge CSV Export Pipeline       ║")
    print("╚══════════════════════════════════════╝\n")

    # Step 1: Load
    print("Step 1: Loading CSV...")
    products = load_csv(csv_path)

    # Step 2: Compliance
    print("Step 2: Running compliance scan...")
    blocked, warnings, clean, changed = compliance.compliance_report(products)
    compliance.write_report(blocked, warnings, clean, changed)
    print(f"  Blocked: {len(blocked)}, Changed: {len(changed)}, Clean: {len(clean)}")

    uploadable = clean + changed
    if not uploadable:
        print("\nNo products passed compliance.")
        return

    # Step 3: Categorize + Price
    print(f"\nStep 3: Categorizing and pricing {len(uploadable)} products...")
    export_products = []
    category_counts = {}
    sku_counter = 1

    for p in uploadable:
        title = categorizer.clean_title(p["title"])
        handle, score, parent = categorizer.categorize(title)
        category_counts[handle] = category_counts.get(handle, 0) + 1
        scale = categorizer.detect_scale(p.get("title", title))

        price_gbp = _parse_price(p.get("raw_price", "0"))
        shipping_gbp = _parse_price(p.get("raw_shipping", "0"))
        sell_usd, compare_usd = calculate_price(price_gbp, shipping_gbp)

        body_html = categorizer.generate_description(title, handle, scale)
        parent_name = categorizer.PARENT_DISPLAY_NAMES.get(parent, "Collectible") if parent else "Collectible"

        image_url = p.get("image_url", "")
        images_raw = p.get("images", "")
        if images_raw:
            first_full = images_raw.split("|")[0].strip()
            if first_full:
                image_url = first_full

        export_products.append({
            "title": title,
            "body_html": body_html,
            "product_type": parent_name,
            "tags": "new",
            "price": sell_usd,
            "compare_at_price": compare_usd,
            "image_url": image_url,
            "images": images_raw,
            "category_handle": handle,
            "parent_handle": parent,
            "seo_title": categorizer.generate_seo_title(title),
            "seo_description": categorizer.generate_seo_description(title),
            "sku": f"CF-{sku_counter:06d}",
        })
        sku_counter += 1

    # Category breakdown
    print(f"\n  {'Category':<35} {'Count':>5}")
    print(f"  {'-'*40}")
    for handle in sorted(category_counts, key=category_counts.get, reverse=True):
        name = categorizer.CATEGORY_DISPLAY_NAMES.get(handle, handle)
        print(f"  {name:<35} {category_counts[handle]:>5}")

    # Step 4: Export
    output_path = csv_path.replace(".csv", "_shopify_import.csv")
    if output_path == csv_path:
        output_path = "shopify_import.csv"

    print(f"\nStep 4: Exporting Shopify CSV...")
    export_shopify_csv(export_products, output_path)

    print(f"\n  {'='*50}")
    print(f"  Export complete!")
    print(f"  Products:    {len(export_products)}")
    print(f"  Blocked:     {len(blocked)}")
    print(f"  Output:      {output_path}")
    print(f"  {'='*50}")
    print(f"\n  Import via: Shopify Admin → Products → Import → {output_path}")


def cmd_scrape(urls_file):
    """Scrape AliExpress product URLs to CSV."""
    print("\n══════════════════════════════════════")
    print("  CastForge AliExpress Scraper")
    print("══════════════════════════════════════\n")

    from scraper import scrape_urls
    output = urls_file.replace(".txt", "_scraped.csv")
    if output == urls_file:
        output = "scraped_products.csv"
    scrape_urls(urls_file, output)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

USAGE = """
CastForge Pipeline CLI

Usage:
  python main.py comply <input.csv>         Title compliance scan
  python main.py comply-images <input.csv>  Image compliance scan (Claude Vision)
  python main.py upload <input.csv>         Full pipeline: comply → categorize → upload
  python main.py export <input.csv>         Comply → categorize → Shopify CSV export
  python main.py stats <input.csv>          Category breakdown (no upload)
  python main.py scrape <urls.txt>          Scrape AliExpress URLs to CSV
  python main.py audit                      Audit existing Shopify products
  streamlit run dashboard.py                Web dashboard UI
"""

COMMANDS_WITH_FILE = ("comply", "comply-images", "upload", "export", "stats", "scrape")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(1)

    command = sys.argv[1]

    if command in COMMANDS_WITH_FILE and len(sys.argv) < 3:
        print(f"Error: {command} requires an input file")
        print(USAGE)
        sys.exit(1)

    if command == "comply":
        cmd_comply(sys.argv[2])
    elif command == "comply-images":
        cmd_comply_images(sys.argv[2])
    elif command == "upload":
        cmd_upload(sys.argv[2])
    elif command == "export":
        cmd_export(sys.argv[2])
    elif command == "stats":
        cmd_stats(sys.argv[2])
    elif command == "scrape":
        cmd_scrape(sys.argv[2])
    elif command == "audit":
        cmd_audit()
    else:
        print(f"Unknown command: {command}")
        print(USAGE)
        sys.exit(1)
