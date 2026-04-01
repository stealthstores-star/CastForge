"""
CastForge AliExpress Scraper

Fast async HTTP scraper using aiohttp with 50 concurrent connections.
Fetches product data from AliExpress's embedded JSON (no JS rendering needed).
Falls back to Playwright for URLs that fail the HTTP method.

Usage:
    python main.py scrape urls.txt                    # Scrape all URLs
    python main.py scrape urls.txt --limit 20         # First 20 only

Performance: ~10,000 URLs in under 30 minutes.
"""

import asyncio
import csv
import json
import os
import random
import re
import sys
import time
from urllib.parse import urlparse

# ═══════════════════════════════════════════════════════════════
# USER AGENT ROTATION
# ═══════════════════════════════════════════════════════════════

USER_AGENTS = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.193 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

CONCURRENCY = 50
DELAY_PER_REQUEST = 0.5  # seconds


def _random_ua():
    return random.choice(USER_AGENTS)


def _extract_product_id(url):
    """Extract numeric product ID from an AliExpress URL."""
    m = re.search(r"(?:/item/|productId=)(\d+)", url)
    return m.group(1) if m else None


# ═══════════════════════════════════════════════════════════════
# ASYNC HTTP SCRAPER (primary method)
# ═══════════════════════════════════════════════════════════════

async def _fetch_product_async(session, url, semaphore, delay=DELAY_PER_REQUEST):
    """Fetch a single product via HTTP, extracting embedded JSON."""
    product_id = _extract_product_id(url)
    if not product_id:
        return None

    async with semaphore:
        await asyncio.sleep(delay * random.uniform(0.5, 1.5))

        headers = {
            "User-Agent": _random_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Referer": "https://www.aliexpress.com/",
        }

        # Try multiple endpoints
        endpoints = [
            f"https://www.aliexpress.com/item/{product_id}.html",
            f"https://m.aliexpress.com/item/{product_id}.html",
        ]

        for endpoint in endpoints:
            try:
                async with session.get(endpoint, headers=headers, timeout=15,
                                       allow_redirects=True, ssl=False) as resp:
                    if resp.status != 200:
                        continue
                    text = await resp.text()
                    product = _parse_page_html(text, url, product_id)
                    if product and product.get("product_title"):
                        return product
            except Exception:
                continue

        return None


def _parse_page_html(html, original_url, product_id):
    """
    Parse product data from AliExpress page HTML.
    AliExpress embeds JSON data in script tags — no JS rendering needed.
    """
    product = _empty_product(original_url, product_id)

    # Strategy 1: window.__INIT_DATA__ (new AliExpress layout)
    m = re.search(r'window\.__INIT_DATA__\s*=\s*(\{.+?\})\s*;?\s*</script>', html, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            return _extract_from_init_data(data, product)
        except (json.JSONDecodeError, KeyError):
            pass

    # Strategy 2: window.runParams (older layout)
    m = re.search(r'data:\s*(\{"actionModule".+?\})\s*[,;}\n]', html, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            return _extract_from_run_params(data, product)
        except (json.JSONDecodeError, KeyError):
            pass

    # Strategy 3: Regex fallback for basic fields
    return _extract_with_regex(html, product)


def _empty_product(url, product_id):
    return {
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


def _extract_from_init_data(data, product):
    """Extract from the __INIT_DATA__ JSON structure."""
    # Navigate the nested structure — keys vary but common patterns exist
    for key, section in data.items():
        if not isinstance(section, dict):
            continue

        # Look for product info in various nested locations
        if "productInfoComponent" in str(section)[:200]:
            _deep_extract(section, product)
        elif "skuModule" in str(section)[:200]:
            _deep_extract(section, product)

    # Fallback: search all values for product-like data
    if not product["product_title"]:
        _deep_extract(data, product)

    return product


def _deep_extract(obj, product):
    """Recursively search a nested dict for product fields."""
    if isinstance(obj, dict):
        # Title
        for key in ("subject", "title", "productTitle"):
            if key in obj and isinstance(obj[key], str) and len(obj[key]) > 10:
                if not product["product_title"]:
                    product["product_title"] = obj[key]

        # Price
        for key in ("formattedActivityPrice", "formattedPrice", "minPrice",
                     "discountPrice", "activityPrice"):
            if key in obj and obj[key]:
                val = str(obj[key])
                if re.search(r"[\d.]+", val):
                    if not product["product_price"]:
                        product["product_price"] = val

        # Original price
        for key in ("formattedOriginalPrice", "maxPrice", "originalPrice"):
            if key in obj and obj[key]:
                if not product["product_original_price"]:
                    product["product_original_price"] = str(obj[key])

        # Images
        if "imagePathList" in obj and isinstance(obj["imagePathList"], list):
            imgs = []
            for img in obj["imagePathList"]:
                if isinstance(img, str) and img:
                    url = img if img.startswith("http") else f"https:{img}"
                    imgs.append(url)
            if imgs and not product["product_images"]:
                product["product_image"] = imgs[0]
                product["product_images"] = "|".join(imgs)

        # Store
        for key in ("storeName", "shopName"):
            if key in obj and isinstance(obj[key], str):
                if not product["store_name"]:
                    product["store_name"] = obj[key]

        # Sales
        for key in ("tradeCount", "totalSales", "soldCount"):
            if key in obj:
                if not product["total_sales"]:
                    product["total_sales"] = str(obj[key])
                    product["trade_info"] = str(obj[key])

        # Shipping
        if "freightResult" in obj or "shippingFee" in obj:
            fee = obj.get("freightResult", obj.get("shippingFee", ""))
            if isinstance(fee, dict):
                cost = fee.get("freightAmount", fee.get("cent", 0))
                product["shipping"] = str(cost) if cost else "0"
            elif fee == "Free Shipping" or (isinstance(fee, str) and "free" in fee.lower()):
                product["shipping"] = "0"

        # Variations / SKU
        if "skuPriceList" in obj and isinstance(obj["skuPriceList"], list):
            _extract_variations_from_sku_list(obj, product)
        elif "productSKUPropertyList" in obj:
            _extract_variations_from_property_list(obj, product)

        # Recurse into values
        for v in obj.values():
            if isinstance(v, (dict, list)):
                _deep_extract(v, product)

    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                _deep_extract(item, product)


def _extract_variations_from_sku_list(obj, product):
    """Extract variations from skuPriceList format."""
    sku_list = obj.get("skuPriceList", [])
    prop_list = obj.get("productSKUPropertyList", [])

    # Determine option name
    option_name = "Style"
    if prop_list:
        for prop in prop_list:
            name = prop.get("skuPropertyName", "")
            if name:
                option_name = name
                break

    variations = []
    for sku in sku_list:
        var = {
            "name": "",
            "price": "",
            "image": "",
            "option_name": option_name,
            "available": True,
        }

        # Name from property values
        prop_val = sku.get("skuAttr", "") or sku.get("skuPropIds", "")
        var["name"] = prop_val

        # Price
        price_data = sku.get("skuVal", {})
        if isinstance(price_data, dict):
            var["price"] = str(price_data.get("actSkuCalPrice",
                              price_data.get("skuCalPrice",
                              price_data.get("actSkuMultiCurrencyCalPrice", ""))))

        # Availability
        if price_data.get("availQuantity", 1) == 0:
            var["available"] = False

        if var["name"] or var["price"]:
            variations.append(var)

    # Map variation images from property list
    if prop_list and variations:
        img_map = {}
        for prop in prop_list:
            for val in prop.get("skuPropertyValues", []):
                pid = str(val.get("propertyValueId", ""))
                img = val.get("skuPropertyImagePath", "")
                name = val.get("propertyValueDisplayName",
                              val.get("propertyValueName", ""))
                if img:
                    img = img if img.startswith("http") else f"https:{img}"
                    img_map[pid] = img
                # Update variation names
                for v in variations:
                    if pid in str(v["name"]):
                        v["name"] = name
                        if pid in img_map:
                            v["image"] = img_map[pid]

    if variations:
        product["variations"] = json.dumps(variations, ensure_ascii=False)
        var_imgs = {v["name"]: v["image"] for v in variations if v.get("image")}
        if var_imgs:
            product["variation_images"] = json.dumps(var_imgs, ensure_ascii=False)


def _extract_variations_from_property_list(obj, product):
    """Extract from productSKUPropertyList directly."""
    prop_list = obj["productSKUPropertyList"]
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


def _extract_from_run_params(data, product):
    """Extract from the older runParams/actionModule JSON structure."""
    # Title
    title_mod = data.get("titleModule", {})
    product["product_title"] = title_mod.get("subject", "")

    # Price
    price_mod = data.get("priceModule", {})
    product["product_price"] = price_mod.get("formattedActivityPrice",
                                price_mod.get("formattedPrice", ""))
    product["product_original_price"] = price_mod.get("formattedOriginalPrice", "")

    # Images
    img_mod = data.get("imageModule", {})
    imgs = img_mod.get("imagePathList", [])
    if imgs:
        product["product_image"] = imgs[0] if imgs[0].startswith("http") else f"https:{imgs[0]}"
        product["product_images"] = "|".join(
            i if i.startswith("http") else f"https:{i}" for i in imgs
        )

    # Store
    store_mod = data.get("storeModule", {})
    product["store_name"] = store_mod.get("storeName", "")
    product["store_url"] = store_mod.get("storeURL", "")

    # Sales
    trade_mod = data.get("tradeModule", {})
    product["total_sales"] = str(trade_mod.get("tradeCount", ""))
    product["trade_info"] = product["total_sales"]

    # Shipping
    ship_mod = data.get("shippingModule", {})
    general_freight = ship_mod.get("generalFreightInfo", {})
    product["shipping"] = str(general_freight.get("originalLayoutResultList", [{}])[0]
                              .get("bizData", {}).get("displayAmount", "0"))

    # Variations
    sku_mod = data.get("skuModule", {})
    if sku_mod:
        _extract_variations_from_sku_list(sku_mod, product)

    return product


def _extract_with_regex(html, product):
    """Last-resort regex extraction from raw HTML."""
    # Title
    m = re.search(r'<title>([^<]+?)(?:\s*[-|])', html)
    if m:
        product["product_title"] = m.group(1).strip()

    # Price
    m = re.search(r'"formattedActivityPrice"\s*:\s*"([^"]+)"', html)
    if not m:
        m = re.search(r'"minPrice"\s*:\s*"?([\d.]+)"?', html)
    if m:
        product["product_price"] = m.group(1)

    # Images
    imgs = re.findall(r'"imageUrl"\s*:\s*"(https?://[^"]+alicdn[^"]+)"', html)
    if not imgs:
        imgs = re.findall(r'"imagePathList"\s*:\s*\[([^\]]+)\]', html)
        if imgs:
            imgs = re.findall(r'"(//[^"]+)"', imgs[0])
            imgs = [f"https:{i}" for i in imgs]
    if imgs:
        product["product_image"] = imgs[0]
        product["product_images"] = "|".join(imgs[:10])

    return product


# ═══════════════════════════════════════════════════════════════
# ASYNC BATCH ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════

async def _scrape_batch_async(urls):
    """Scrape all URLs concurrently using aiohttp."""
    import aiohttp

    semaphore = asyncio.Semaphore(CONCURRENCY)
    results = []
    failed_urls = []

    connector = aiohttp.TCPConnector(limit=CONCURRENCY, ttl_dns_cache=300)
    timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        tasks = []
        for url in urls:
            tasks.append(_fetch_product_async(session, url, semaphore))

        # Process with progress
        total = len(tasks)
        completed = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            completed += 1
            if result and result.get("product_title"):
                results.append(result)
            else:
                # Find which URL failed (by index tracking)
                failed_urls.append(urls[completed - 1] if completed <= len(urls) else "")

            if completed % 50 == 0 or completed == total:
                print(f"  [{completed}/{total}] {len(results)} scraped, "
                      f"{completed - len(results)} failed")

    return results, failed_urls


# ═══════════════════════════════════════════════════════════════
# PLAYWRIGHT FALLBACK (for failed URLs)
# ═══════════════════════════════════════════════════════════════

def _playwright_fallback(urls):
    """Fallback scraper for URLs that failed the async HTTP method."""
    if not urls:
        return []

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(f"  Playwright not installed — skipping {len(urls)} failed URLs")
        return []

    print(f"\n  Playwright fallback for {len(urls)} failed URLs...")
    products = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=_random_ua(),
                                       viewport={"width": 1920, "height": 1080})
        for i, url in enumerate(urls[:100]):  # Cap at 100 for fallback
            try:
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(2000)

                product_id = _extract_product_id(url)
                product = _empty_product(url, product_id or "")
                html = page.content()
                product = _parse_page_html(html, url, product_id or "")

                if product.get("product_title"):
                    products.append(product)

                page.close()
                if i < len(urls) - 1:
                    time.sleep(1)
            except Exception:
                pass

        browser.close()

    print(f"  Playwright recovered {len(products)}/{len(urls)} products")
    return products


# ═══════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════

def scrape_urls(urls_file, output_csv="scraped_products.csv", limit=None):
    """
    Scrape AliExpress URLs from a text file.
    Primary: async HTTP with 50 concurrent connections.
    Fallback: Playwright for failed URLs.
    """
    with open(urls_file) as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    if limit:
        urls = urls[:limit]

    total = len(urls)
    print(f"  {total} URLs to scrape ({CONCURRENCY} concurrent connections)\n")

    start = time.time()

    # Primary: async HTTP
    products, failed_urls = asyncio.run(_scrape_batch_async(urls))
    elapsed = time.time() - start
    print(f"\n  Async HTTP: {len(products)} scraped in {elapsed:.1f}s "
          f"({len(products)/max(elapsed,1):.0f} URLs/s)")

    # Fallback: Playwright for failures
    if failed_urls:
        print(f"  {len(failed_urls)} URLs failed HTTP — trying Playwright fallback...")
        recovered = _playwright_fallback(failed_urls)
        products.extend(recovered)

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
            for prod in products:
                writer.writerow(prod)

        total_time = time.time() - start
        print(f"\n  Saved {len(products)} products → {output_csv}")
        print(f"  Total time: {total_time:.1f}s ({len(products)/max(total_time,1):.0f} products/s)")
    else:
        print("\n  No products scraped successfully.")

    return products
