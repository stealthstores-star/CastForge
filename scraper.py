"""
CastForge AliExpress Scraper

Playwright-based scraper with 5 concurrent browser tabs, stealth mode,
and checkpoint resuming. Designed for 1,500+ URL batches.

Usage:
    python main.py scrape urls.txt                    # All URLs
    python main.py scrape urls.txt --limit 50         # First 50 only

Performance: ~1,500 URLs in 15 minutes (5 tabs × 3s avg per page).
"""

import csv
import json
import os
import random
import re
import sys
import time
import asyncio
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

CONCURRENT_TABS = 5
MIN_DELAY = 4.0
MAX_DELAY = 8.0
CHECKPOINT_INTERVAL = 10  # Save progress every N products
CHECKPOINT_FILE = Path("scrape_checkpoint.json")

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]

CSV_FIELDNAMES = [
    "id", "product_title", "product_price", "product_original_price",
    "product_discount", "product_url", "product_image", "product_images",
    "product_rating", "store_name", "store_url", "store_id",
    "total_sales", "ship_from", "store_member_id", "trade_info",
    "shipping", "launch_time", "company_name", "source_url",
    "variations", "variation_images",
]


def _random_delay():
    return random.uniform(MIN_DELAY, MAX_DELAY)


def _extract_product_id(url):
    m = re.search(r"(?:/item/|productId=)(\d+)", url)
    return m.group(1) if m else None


# ═══════════════════════════════════════════════════════════════
# CHECKPOINT (resume after crash)
# ═══════════════════════════════════════════════════════════════

def _load_checkpoint():
    if CHECKPOINT_FILE.exists():
        data = json.loads(CHECKPOINT_FILE.read_text())
        return set(data.get("scraped_urls", [])), data.get("products", [])
    return set(), []


def _save_checkpoint(scraped_urls, products):
    CHECKPOINT_FILE.write_text(json.dumps({
        "scraped_urls": list(scraped_urls),
        "products": products,
    }, ensure_ascii=False))


def _clear_checkpoint():
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()


# ═══════════════════════════════════════════════════════════════
# STEALTH SETUP
# ═══════════════════════════════════════════════════════════════

def _apply_stealth(page):
    """Apply stealth patches to avoid bot detection."""
    page.add_init_script("""
        // Override navigator.webdriver
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

        // Override navigator.plugins
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });

        // Override navigator.languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
        });

        // Chrome runtime
        window.chrome = { runtime: {} };

        // Permissions
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) =>
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters);
    """)


# ═══════════════════════════════════════════════════════════════
# SINGLE PAGE SCRAPER
# ═══════════════════════════════════════════════════════════════

def _scrape_page(context, url):
    """Scrape a single AliExpress product page."""
    product_id = _extract_product_id(url)
    if not product_id:
        return None

    page = context.new_page()
    _apply_stealth(page)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(int(_random_delay() * 1000))

        product = {
            "id": product_id,
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

        # ── Try embedded JSON first (fastest) ──
        html = page.content()
        json_product = _extract_from_embedded_json(html, url, product_id)
        if json_product and json_product.get("product_title"):
            return json_product

        # ── Fallback: DOM scraping ──

        # Title
        for sel in ["h1[data-pl='product-title']", "h1.product-title-text", "h1"]:
            el = page.query_selector(sel)
            if el:
                text = el.inner_text().strip()
                if len(text) > 5:
                    product["product_title"] = text
                    break

        # Price
        for sel in ["[class*='Price'] span.es--wrap--erdmPRe",
                     "[class*='price--current'] span",
                     "[class*='Price_price__'] span",
                     "[class*='product-price-value']",
                     ".uniform-banner-box-price"]:
            el = page.query_selector(sel)
            if el:
                product["product_price"] = el.inner_text().strip()
                break

        # Original price
        for sel in ["[class*='Price_originalPrice__']",
                     "[class*='price--original'] span",
                     "[class*='product-price-del']"]:
            el = page.query_selector(sel)
            if el:
                product["product_original_price"] = el.inner_text().strip()
                break

        # Images
        images = []
        for sel in ["img[class*='slider--img']",
                     ".images-view-item img",
                     "[class*='magnifier'] img",
                     "img[class*='pdp-img']"]:
            img_els = page.query_selector_all(sel)
            if img_els:
                for img_el in img_els:
                    src = img_el.get_attribute("src") or ""
                    if src and ("alicdn" in src or "ae01" in src):
                        full = re.sub(r"_\d+x\d+\.\w+$", ".jpg", src)
                        if not full.startswith("http"):
                            full = f"https:{full}"
                        if full not in images:
                            images.append(full)
                break

        if images:
            product["product_image"] = images[0]
            product["product_images"] = "|".join(images)

        # Shipping
        for sel in ["[class*='dynamic-shipping'] span[class*='bold']",
                     "[class*='shipping-value']",
                     "[class*='dynamic-shipping-line']"]:
            el = page.query_selector(sel)
            if el:
                text = el.inner_text().strip()
                if "free" in text.lower():
                    product["shipping"] = "0"
                else:
                    m = re.search(r"[\£\$€]?([\d.]+)", text)
                    if m:
                        product["shipping"] = m.group(1)
                break

        # Store name
        for sel in ["[class*='store-name'] a", "[class*='shop-name'] a",
                     "a[class*='store--name']"]:
            el = page.query_selector(sel)
            if el:
                product["store_name"] = el.inner_text().strip()
                product["store_url"] = el.get_attribute("href") or ""
                break

        # Sales
        for sel in ["[class*='reviewer--sold']",
                     "[class*='product-reviewer-sold']",
                     "span[class*='count--trade']"]:
            el = page.query_selector(sel)
            if el:
                product["total_sales"] = el.inner_text().strip()
                product["trade_info"] = product["total_sales"]
                break

        # Variations
        variations = _scrape_variations(page)
        if variations:
            product["variations"] = json.dumps(variations, ensure_ascii=False)
            var_imgs = {v["name"]: v["image"] for v in variations if v.get("image")}
            if var_imgs:
                product["variation_images"] = json.dumps(var_imgs, ensure_ascii=False)

        if not product["product_title"]:
            return None

        return product

    except Exception as e:
        return None

    finally:
        page.close()


def _extract_from_embedded_json(html, url, product_id):
    """Try to extract product data from embedded JSON in the HTML."""
    product = {
        "id": product_id, "product_title": "", "product_price": "",
        "product_original_price": "", "product_discount": "",
        "product_url": url, "product_image": "", "product_images": "",
        "product_rating": "", "store_name": "", "store_url": "",
        "store_id": "", "total_sales": "", "ship_from": "",
        "store_member_id": "", "trade_info": "", "shipping": "0",
        "launch_time": "", "company_name": "", "source_url": url,
        "variations": "", "variation_images": "",
    }

    # Strategy 1: window.__INIT_DATA__
    m = re.search(r'window\.__INIT_DATA__\s*=\s*(\{.+?\})\s*;?\s*</script>', html, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            _deep_extract(data, product)
            if product.get("product_title"):
                return product
        except (json.JSONDecodeError, KeyError):
            pass

    # Strategy 2: data: {"actionModule"...}
    m = re.search(r'data:\s*(\{"actionModule".+?\})\s*[,;}\n]', html, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            _extract_from_run_params(data, product)
            if product.get("product_title"):
                return product
        except (json.JSONDecodeError, KeyError):
            pass

    return None


def _deep_extract(obj, product):
    """Recursively search nested dict for product fields."""
    if isinstance(obj, dict):
        for key in ("subject", "title", "productTitle"):
            if key in obj and isinstance(obj[key], str) and len(obj[key]) > 10:
                if not product["product_title"]:
                    product["product_title"] = obj[key]

        for key in ("formattedActivityPrice", "formattedPrice", "minPrice",
                     "discountPrice", "activityPrice"):
            if key in obj and obj[key]:
                val = str(obj[key])
                if re.search(r"[\d.]+", val) and not product["product_price"]:
                    product["product_price"] = val

        for key in ("formattedOriginalPrice", "maxPrice", "originalPrice"):
            if key in obj and obj[key] and not product["product_original_price"]:
                product["product_original_price"] = str(obj[key])

        if "imagePathList" in obj and isinstance(obj["imagePathList"], list):
            imgs = []
            for img in obj["imagePathList"]:
                if isinstance(img, str) and img:
                    u = img if img.startswith("http") else f"https:{img}"
                    imgs.append(u)
            if imgs and not product["product_images"]:
                product["product_image"] = imgs[0]
                product["product_images"] = "|".join(imgs)

        for key in ("storeName", "shopName"):
            if key in obj and isinstance(obj[key], str) and not product["store_name"]:
                product["store_name"] = obj[key]

        for key in ("tradeCount", "totalSales", "soldCount", "formatTradeCount"):
            if key in obj and not product["total_sales"]:
                product["total_sales"] = str(obj[key])
                product["trade_info"] = str(obj[key])

        if "productSKUPropertyList" in obj:
            _extract_variations_from_property_list(obj, product)

        for v in obj.values():
            if isinstance(v, (dict, list)):
                _deep_extract(v, product)

    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                _deep_extract(item, product)


def _extract_from_run_params(data, product):
    """Extract from older runParams/actionModule JSON."""
    title_mod = data.get("titleModule", {})
    product["product_title"] = title_mod.get("subject", "")

    price_mod = data.get("priceModule", {})
    product["product_price"] = price_mod.get("formattedActivityPrice",
                                price_mod.get("formattedPrice", ""))
    product["product_original_price"] = price_mod.get("formattedOriginalPrice", "")

    img_mod = data.get("imageModule", {})
    imgs = img_mod.get("imagePathList", [])
    if imgs:
        full = [i if i.startswith("http") else f"https:{i}" for i in imgs]
        product["product_image"] = full[0]
        product["product_images"] = "|".join(full)

    store_mod = data.get("storeModule", {})
    product["store_name"] = store_mod.get("storeName", "")

    sku_mod = data.get("skuModule", {})
    if sku_mod:
        _extract_variations_from_property_list(sku_mod, product)

    return product


def _extract_variations_from_property_list(obj, product):
    """Extract from productSKUPropertyList."""
    prop_list = obj.get("productSKUPropertyList", [])
    if not isinstance(prop_list, list) or not prop_list:
        return

    variations = []
    for prop in prop_list:
        option_name = prop.get("skuPropertyName", "Style")
        for val in prop.get("skuPropertyValues", []):
            var = {
                "name": val.get("propertyValueDisplayName",
                              val.get("propertyValueName", "")),
                "price": "",
                "image": "",
                "option_name": option_name,
                "available": True,
            }
            img = val.get("skuPropertyImagePath", "")
            if img:
                var["image"] = img if img.startswith("http") else f"https:{img}"
            if var["name"]:
                variations.append(var)

    if variations:
        product["variations"] = json.dumps(variations, ensure_ascii=False)
        var_imgs = {v["name"]: v["image"] for v in variations if v.get("image")}
        if var_imgs:
            product["variation_images"] = json.dumps(var_imgs, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# DOM VARIATION SCRAPING
# ═══════════════════════════════════════════════════════════════

def _scrape_variations(page):
    """Extract variation data from DOM elements."""
    variations = []

    # Find variation containers
    for container_sel in ["[class*='sku-item']", "[class*='skuItem']",
                           "[class*='sku-property-item']", "[class*='property-item']"]:
        els = page.query_selector_all(container_sel)
        if els:
            break
    else:
        return []

    # Detect option name
    option_name = "Style"
    for label_sel in ["[class*='sku-title']", "[class*='property-title']",
                       "[class*='sku--title']"]:
        label_el = page.query_selector(label_sel)
        if label_el:
            text = label_el.inner_text().strip().rstrip(":")
            if text:
                option_name = text
            break

    for el in els:
        var = {"name": "", "price": "", "image": "", "option_name": option_name,
               "available": True}

        var["name"] = el.get_attribute("title") or el.inner_text().strip()

        img_el = el.query_selector("img")
        if img_el:
            src = img_el.get_attribute("src") or ""
            if src and ("alicdn" in src or "ae01" in src):
                full = re.sub(r"_\d+x\d+\.\w+$", ".jpg", src)
                var["image"] = full if full.startswith("http") else f"https:{full}"

        classes = el.get_attribute("class") or ""
        if "disabled" in classes or "unavailable" in classes:
            var["available"] = False

        if var["name"]:
            variations.append(var)

    return variations


# ═══════════════════════════════════════════════════════════════
# CONCURRENT SCRAPER (5 tabs)
# ═══════════════════════════════════════════════════════════════

def _scrape_concurrent(context, urls, scraped_urls, products):
    """Scrape URLs using multiple tabs with progress and checkpointing."""
    remaining = [u for u in urls if u not in scraped_urls]
    total_remaining = len(remaining)
    total_all = len(urls)
    already_done = len(scraped_urls)

    if not remaining:
        print(f"  All {total_all} URLs already scraped (from checkpoint)")
        return products

    if already_done > 0:
        print(f"  Resuming from checkpoint: {already_done} done, {total_remaining} remaining\n")

    success = 0
    failed = 0

    # Process in batches of CONCURRENT_TABS
    for batch_start in range(0, total_remaining, CONCURRENT_TABS):
        batch = remaining[batch_start:batch_start + CONCURRENT_TABS]

        for url in batch:
            try:
                product = _scrape_page(context, url)
                if product and product.get("product_title"):
                    products.append(product)
                    scraped_urls.add(url)
                    success += 1
                    var_count = len(json.loads(product.get("variations", "[]") or "[]"))
                    var_info = f" ({var_count} vars)" if var_count else ""
                    title = product["product_title"][:50]
                else:
                    scraped_urls.add(url)
                    failed += 1
                    title = "FAILED"
            except Exception as e:
                scraped_urls.add(url)
                failed += 1
                title = f"ERROR: {str(e)[:40]}"

            done = already_done + success + failed
            if done % 5 == 0 or done == total_all:
                print(f"  [{done}/{total_all}] {success} OK, {failed} fail — {title}")

        # Checkpoint
        if (success + failed) % CHECKPOINT_INTERVAL < CONCURRENT_TABS:
            _save_checkpoint(scraped_urls, products)

    # Final checkpoint
    _save_checkpoint(scraped_urls, products)
    return products


# ═══════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════

def scrape_urls(urls_file, output_csv="scraped_products.csv", limit=None):
    """
    Scrape AliExpress URLs using Playwright with stealth mode.
    5 concurrent tabs, 2-5s random delays, checkpoint resuming.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is required:")
        print("  pip install playwright")
        print("  python -m playwright install chromium")
        sys.exit(1)

    with open(urls_file) as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    if limit:
        urls = urls[:limit]

    # Load checkpoint
    scraped_urls, products = _load_checkpoint()

    total = len(urls)
    print(f"  {total} URLs to scrape ({CONCURRENT_TABS} concurrent tabs, "
          f"{MIN_DELAY}-{MAX_DELAY}s delays)\n")

    start = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
        )

        products = _scrape_concurrent(context, urls, scraped_urls, products)

        browser.close()

    elapsed = time.time() - start

    # Write CSV
    if products:
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
            writer.writeheader()
            for prod in products:
                writer.writerow(prod)

        var_products = sum(1 for p in products if p.get("variations"))
        total_vars = sum(
            len(json.loads(p.get("variations", "[]") or "[]"))
            for p in products if p.get("variations")
        )

        # Save failed URLs
        scraped_product_urls = {p.get("product_url") or p.get("source_url") for p in products}
        failed = [u for u in urls if u not in scraped_product_urls and u not in scraped_urls
                  or (u in scraped_urls and u not in scraped_product_urls)]
        # More reliable: any URL not in successful products
        successful_ids = {p.get("id") for p in products if p.get("id")}
        failed = [u for u in urls
                  if _extract_product_id(u) not in successful_ids]

        failed_file = output_csv.replace(".csv", "_failed.txt")
        if not failed_file.endswith("_failed.txt"):
            failed_file = "failed_urls.txt"
        if failed:
            with open(failed_file, "w") as f:
                for u in failed:
                    f.write(u + "\n")
            print(f"  Failed:        {len(failed)} URLs → {failed_file}")

        print(f"\n  {'='*50}")
        print(f"  Scraped:      {len(products)} products")
        print(f"  Failed:       {len(failed)} URLs")
        print(f"  With variants: {var_products} products ({total_vars} total variants)")
        print(f"  Time:          {elapsed:.0f}s ({len(products)/max(elapsed,1):.1f} products/s)")
        print(f"  Output:        {output_csv}")
        print(f"  {'='*50}")

        # Clear checkpoint on success
        _clear_checkpoint()
    else:
        print("\n  No products scraped successfully.")
        # Save all as failed
        with open("failed_urls.txt", "w") as f:
            for u in urls:
                f.write(u + "\n")
        print(f"  All {len(urls)} URLs saved to failed_urls.txt for retry")

    return products
