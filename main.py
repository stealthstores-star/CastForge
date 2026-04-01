#!/usr/bin/env python3
"""
CastForge Pipeline CLI
Commands:
  python main.py comply <input.csv>         — Run title compliance scan
  python main.py comply-images <input.csv>  — Scan images via Claude Vision
  python main.py upload <input.csv>         — Full pipeline WITH compliance
  python main.py audit                      — Audit existing Shopify products
"""

import csv
import json
import sys
import os

import requests

import config
import compliance


def _get_shopify_token():
    """Exchange client credentials for a Shopify access token."""
    resp = requests.post(
        f"https://{config.SHOPIFY_STORE}/admin/oauth/access_token",
        json={
            "client_id": config.SHOPIFY_CLIENT_ID,
            "client_secret": config.SHOPIFY_CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
    )
    if resp.status_code != 200:
        print(f"Failed to get Shopify token: {resp.status_code} {resp.text[:200]}")
        sys.exit(1)
    return resp.json()["access_token"]


def _shopify_headers():
    token = _get_shopify_token()
    return {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": token,
    }


def load_products_csv(path):
    """Load products from a CSV file. Expects at least a 'title' column."""
    products = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            products.append(dict(row))
    print(f"Loaded {len(products)} products from {path}")
    return products


# ═══════════════════════════════════════════════════════════════
# COMMANDS
# ═══════════════════════════════════════════════════════════════

def cmd_comply(csv_path):
    """Run title compliance scan only (no image scan, no upload)."""
    print("\n══════════════════════════════════════")
    print("  CastForge Title Compliance Scan")
    print("══════════════════════════════════════\n")

    products = load_products_csv(csv_path)
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
        print("Set ANTHROPIC_API_KEY in config.py or environment to scan images.")
        sys.exit(1)

    products = load_products_csv(csv_path)

    # Collect image URLs
    image_urls = []
    for p in products:
        url = p.get("image_url") or p.get("image") or p.get("Image Src") or ""
        if url:
            p["image_url"] = url
            image_urls.append(url)

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


def cmd_upload(csv_path):
    """Full pipeline: compliance scan then upload clean products to Shopify."""
    print("\n══════════════════════════════════════")
    print("  CastForge Full Upload Pipeline")
    print("══════════════════════════════════════\n")

    products = load_products_csv(csv_path)

    # Step 1: Title compliance
    print("Step 1: Running title compliance scan...")
    blocked, warnings, clean, changed = compliance.compliance_report(products)

    # Step 2: Optional image compliance
    if config.SCAN_IMAGES and config.ANTHROPIC_API_KEY != "sk-ant-xxx":
        print("Step 2: Running image compliance scan...")
        image_urls = [p.get("image_url", "") for p in products if p.get("image_url")]
        if image_urls:
            image_results = compliance.scan_images_batch(image_urls)
            blocked2, warnings2, clean2, changed2 = compliance.compliance_report(
                clean + [c for c in changed], image_results
            )
            blocked.extend(blocked2)
            warnings.extend(warnings2)
            clean = clean2
            changed = changed2
    else:
        print("Step 2: Image scanning skipped (no API key or disabled)")

    compliance.write_report(blocked, warnings, clean, changed)

    uploadable = clean + [p for p in changed if p not in warnings]
    print(f"\nReady to upload: {len(uploadable)} products")
    print(f"Blocked: {len(blocked)}, Warnings: {len(warnings)}")

    if not uploadable:
        print("No products to upload.")
        return

    # Step 3: Upload to Shopify
    print("\nStep 3: Uploading to Shopify...")
    headers = _shopify_headers()
    base_url = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    # Load collection map if available
    collection_map = {}
    if os.path.exists("collection_map.json"):
        with open("collection_map.json") as f:
            collection_map = json.load(f)

    success = 0
    failed = 0
    for i, product in enumerate(uploadable):
        payload = {
            "product": {
                "title": product.get("title", ""),
                "body_html": product.get("description", product.get("body_html", "")),
                "vendor": "CastForge",
                "product_type": product.get("product_type", ""),
                "status": "draft",
            }
        }

        # Add image if available
        img = product.get("image_url") or product.get("image") or product.get("Image Src")
        if img:
            payload["product"]["images"] = [{"src": img}]

        resp = requests.post(f"{base_url}/products.json", headers=headers, json=payload)
        if resp.status_code == 201:
            success += 1
        else:
            failed += 1
            if failed <= 5:
                print(f"  Failed: {product.get('title', '?')[:50]} — {resp.status_code}")

        if (i + 1) % 50 == 0:
            print(f"  Uploaded {i+1}/{len(uploadable)}...")

    print(f"\nUpload complete: {success} succeeded, {failed} failed")


def cmd_audit():
    """Audit all existing Shopify products for compliance issues."""
    print("\n══════════════════════════════════════")
    print("  CastForge Product Audit")
    print("══════════════════════════════════════\n")

    headers = _shopify_headers()
    base_url = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    # Fetch all products
    products = []
    url = f"{base_url}/products.json?limit=250&fields=id,title,handle,status"
    while url:
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            print(f"API error: {resp.status_code}")
            sys.exit(1)
        data = resp.json()
        products.extend(data.get("products", []))

        # Pagination via Link header
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

    # Save audit report
    if issues_found:
        with open("audit_results.json", "w") as f:
            json.dump(issues_found, f, indent=2)
        print(f"Saved audit_results.json ({len(issues_found)} issues)")


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

USAGE = """
Usage:
  python main.py comply <input.csv>         Title compliance scan
  python main.py comply-images <input.csv>  Image compliance scan (Claude Vision)
  python main.py upload <input.csv>         Full pipeline with compliance
  python main.py audit                      Audit existing Shopify products
"""

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(1)

    command = sys.argv[1]

    if command in ("comply", "comply-images", "upload") and len(sys.argv) < 3:
        print(f"Error: {command} requires an input CSV file")
        print(USAGE)
        sys.exit(1)

    if command == "comply":
        cmd_comply(sys.argv[2])
    elif command == "comply-images":
        cmd_comply_images(sys.argv[2])
    elif command == "upload":
        cmd_upload(sys.argv[2])
    elif command == "audit":
        cmd_audit()
    else:
        print(f"Unknown command: {command}")
        print(USAGE)
        sys.exit(1)
