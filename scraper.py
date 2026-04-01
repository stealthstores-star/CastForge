"""
CastForge AliExpress URL Scraper
Scrapes product data from AliExpress product pages using Playwright.
Outputs a CSV compatible with the CastForge pipeline.

Usage:
    python main.py scrape urls.txt
"""

import csv
import json
import re
import sys
import time


def scrape_urls(urls_file, output_csv="scraped_products.csv"):
    """
    Read a text file of AliExpress URLs (one per line) and scrape each.
    Outputs a CSV with columns matching the pipeline format.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is required for scraping.")
        print("Install it with:")
        print("  pip install playwright")
        print("  playwright install chromium")
        sys.exit(1)

    # Read URLs
    with open(urls_file) as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    print(f"  Found {len(urls)} URLs to scrape\n")
    products = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )

        for i, url in enumerate(urls):
            print(f"  [{i+1}/{len(urls)}] Scraping: {url[:80]}...")
            try:
                product = _scrape_single(context, url)
                if product:
                    products.append(product)
                    print(f"    ✓ {product['product_title'][:60]}")
                else:
                    print(f"    ✗ Failed to extract data")
            except Exception as e:
                print(f"    ✗ Error: {str(e)[:100]}")

            # Rate limiting
            if i < len(urls) - 1:
                time.sleep(2)

        browser.close()

    # Write CSV
    if products:
        fieldnames = [
            "id", "product_title", "product_price", "product_original_price",
            "product_discount", "product_url", "product_image", "product_images",
            "product_rating", "store_name", "store_url", "store_id",
            "total_sales", "ship_from", "store_member_id", "trade_info",
            "shipping", "launch_time", "company_name", "source_url",
            "variations", "variation_images",
        ]
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for p in products:
                writer.writerow(p)

        print(f"\n  Saved {len(products)} products → {output_csv}")
    else:
        print("\n  No products scraped successfully.")

    return products


def _scrape_single(context, url):
    """Scrape a single AliExpress product page."""
    page = context.new_page()

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)  # Let JS render

        product = {
            "id": "",
            "product_title": "",
            "product_price": "",
            "product_original_price": "",
            "product_discount": "",
            "product_url": url,
            "product_image": "",
            "product_images": "",
            "product_rating": "",
            "store_name": "",
            "store_url": "",
            "store_id": "",
            "total_sales": "",
            "ship_from": "",
            "store_member_id": "",
            "trade_info": "",
            "shipping": "0",
            "launch_time": "",
            "company_name": "",
            "source_url": url,
            "variations": "",
            "variation_images": "",
        }

        # Extract product ID from URL
        m = re.search(r"/item/(\d+)", url)
        if m:
            product["id"] = m.group(1)

        # Title
        title_el = page.query_selector("h1[data-pl='product-title']")
        if not title_el:
            title_el = page.query_selector("h1")
        if title_el:
            product["product_title"] = title_el.inner_text().strip()

        # Price — try multiple selectors
        price_el = page.query_selector("[class*='Price_price__'] span")
        if not price_el:
            price_el = page.query_selector("[class*='product-price-value']")
        if not price_el:
            price_el = page.query_selector(".uniform-banner-box-price")
        if price_el:
            raw_price = price_el.inner_text().strip()
            product["product_price"] = raw_price

        # Original price
        orig_el = page.query_selector("[class*='Price_originalPrice__']")
        if not orig_el:
            orig_el = page.query_selector("[class*='product-price-del']")
        if orig_el:
            product["product_original_price"] = orig_el.inner_text().strip()

        # Images
        images = []
        img_els = page.query_selector_all("img[class*='slider--img']")
        if not img_els:
            img_els = page.query_selector_all(".images-view-item img")
        if not img_els:
            img_els = page.query_selector_all("[class*='magnifier'] img")

        for img_el in img_els:
            src = img_el.get_attribute("src") or ""
            if src and "alicdn" in src:
                # Get full-size image
                full_src = re.sub(r"_\d+x\d+\.\w+$", ".jpg", src)
                if full_src not in images:
                    images.append(full_src)

        if images:
            product["product_image"] = images[0]
            product["product_images"] = "|".join(images)

        # Shipping cost
        ship_el = page.query_selector("[class*='shipping-value']")
        if not ship_el:
            ship_el = page.query_selector("[class*='dynamic-shipping-line']")
        if ship_el:
            ship_text = ship_el.inner_text().strip()
            if "free" in ship_text.lower():
                product["shipping"] = "0"
            else:
                m = re.search(r"[\£\$€]?([\d.]+)", ship_text)
                if m:
                    product["shipping"] = m.group(1)

        # Store name
        store_el = page.query_selector("[class*='store-name'] a")
        if not store_el:
            store_el = page.query_selector("[class*='shop-name'] a")
        if store_el:
            product["store_name"] = store_el.inner_text().strip()
            product["store_url"] = store_el.get_attribute("href") or ""

        # Sales count
        sales_el = page.query_selector("[class*='reviewer--sold']")
        if not sales_el:
            sales_el = page.query_selector("[class*='product-reviewer-sold']")
        if sales_el:
            product["total_sales"] = sales_el.inner_text().strip()
            product["trade_info"] = product["total_sales"]

        if not product["product_title"]:
            return None

        return product

    finally:
        page.close()
