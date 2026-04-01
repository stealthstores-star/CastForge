"""
CastForge AliExpress Scraper

3 parallel browsers, each processing 25 URLs before full restart.
75 URLs per cycle, 15s cooldown between cycles.
~1,500 URLs in ~55 minutes.

Usage:
    cd ~/CastForge && python3 main.py scrape links_part2.txt
    cd ~/CastForge && python3 main.py scrape links_part2.txt --limit 150
"""

import csv
import json
import os
import random
import re
import sys
import time
import threading
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

BROWSERS = 3              # Parallel browser instances
URLS_PER_BROWSER = 25     # URLs before browser dies and respawns
TABS_PER_BROWSER = 2      # Concurrent tabs within each browser
MIN_DELAY = 3.0           # Min seconds between pages
MAX_DELAY = 6.0           # Max seconds between pages
COOLDOWN = 15             # Seconds between browser respawn cycles
CHECKPOINT_INTERVAL = 25  # Save progress every N products

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
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]

CSV_FIELDNAMES = [
    "id", "product_title", "product_price", "product_original_price",
    "product_discount", "product_url", "product_image", "product_images",
    "product_rating", "store_name", "store_url", "store_id",
    "total_sales", "ship_from", "store_member_id", "trade_info",
    "shipping", "launch_time", "company_name", "source_url",
    "variations", "variation_images",
]


def _extract_product_id(url):
    m = re.search(r"(?:/item/|productId=)(\d+)", url)
    return m.group(1) if m else None


def _random_viewport():
    w = random.choice([1280, 1366, 1440, 1536, 1680, 1920])
    h = random.choice([720, 768, 900, 1024, 1080])
    return {"width": w, "height": h}


# ═══════════════════════════════════════════════════════════════
# CHECKPOINT
# ═══════════════════════════════════════════════════════════════

_checkpoint_lock = threading.Lock()


def _load_checkpoint():
    if CHECKPOINT_FILE.exists():
        data = json.loads(CHECKPOINT_FILE.read_text())
        return set(data.get("scraped_ids", [])), data.get("products", [])
    return set(), []


def _save_checkpoint(scraped_ids, products):
    with _checkpoint_lock:
        CHECKPOINT_FILE.write_text(json.dumps({
            "scraped_ids": list(scraped_ids),
            "products": products,
        }, ensure_ascii=False))


def _clear_checkpoint():
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()


# ═══════════════════════════════════════════════════════════════
# STEALTH
# ═══════════════════════════════════════════════════════════════

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
window.chrome = { runtime: {} };
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters);
"""


# ═══════════════════════════════════════════════════════════════
# SINGLE PAGE SCRAPER
# ═══════════════════════════════════════════════════════════════

def _scrape_page(context, url):
    """Scrape one AliExpress product page."""
    product_id = _extract_product_id(url)
    if not product_id:
        return None

    page = context.new_page()
    page.add_init_script(STEALTH_JS)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(int(random.uniform(MIN_DELAY, MAX_DELAY) * 1000))

        product = {
            "id": product_id,
            "product_title": "", "product_price": "",
            "product_original_price": "", "product_discount": "",
            "product_url": url, "product_image": "", "product_images": "",
            "product_rating": "", "store_name": "", "store_url": "",
            "store_id": "", "total_sales": "", "ship_from": "",
            "store_member_id": "", "trade_info": "", "shipping": "0",
            "launch_time": "", "company_name": "", "source_url": url,
            "variations": "", "variation_images": "",
        }

        html = page.content()

        # Try embedded JSON first
        json_product = _extract_from_embedded_json(html, url, product_id)
        if json_product and json_product.get("product_title"):
            return json_product

        # DOM fallback
        for sel in ["h1[data-pl='product-title']", "h1.product-title-text", "h1"]:
            el = page.query_selector(sel)
            if el:
                text = el.inner_text().strip()
                if len(text) > 5:
                    product["product_title"] = text
                    break

        for sel in ["[class*='Price'] span.es--wrap--erdmPRe",
                     "[class*='price--current'] span",
                     "[class*='Price_price__'] span",
                     "[class*='product-price-value']"]:
            el = page.query_selector(sel)
            if el:
                product["product_price"] = el.inner_text().strip()
                break

        for sel in ["[class*='Price_originalPrice__']",
                     "[class*='price--original'] span"]:
            el = page.query_selector(sel)
            if el:
                product["product_original_price"] = el.inner_text().strip()
                break

        images = []
        for sel in ["img[class*='slider--img']", ".images-view-item img",
                     "[class*='magnifier'] img", "img[class*='pdp-img']"]:
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

        for sel in ["[class*='dynamic-shipping'] span[class*='bold']",
                     "[class*='shipping-value']"]:
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

        for sel in ["[class*='store-name'] a", "a[class*='store--name']"]:
            el = page.query_selector(sel)
            if el:
                product["store_name"] = el.inner_text().strip()
                break

        for sel in ["[class*='reviewer--sold']", "span[class*='count--trade']"]:
            el = page.query_selector(sel)
            if el:
                product["total_sales"] = el.inner_text().strip()
                product["trade_info"] = product["total_sales"]
                break

        # Variations from DOM
        variations = _scrape_variations_dom(page)
        if variations:
            product["variations"] = json.dumps(variations, ensure_ascii=False)
            var_imgs = {v["name"]: v["image"] for v in variations if v.get("image")}
            if var_imgs:
                product["variation_images"] = json.dumps(var_imgs, ensure_ascii=False)

        return product if product.get("product_title") else None

    except Exception:
        return None
    finally:
        page.close()


# ═══════════════════════════════════════════════════════════════
# JSON EXTRACTION
# ═══════════════════════════════════════════════════════════════

def _extract_from_embedded_json(html, url, product_id):
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

    m = re.search(r'window\.__INIT_DATA__\s*=\s*(\{.+?\})\s*;?\s*</script>', html, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            _deep_extract(data, product)
            if product.get("product_title"):
                return product
        except (json.JSONDecodeError, KeyError):
            pass

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
            _extract_variations_json(obj, product)

        for v in obj.values():
            if isinstance(v, (dict, list)):
                _deep_extract(v, product)

    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                _deep_extract(item, product)


def _extract_from_run_params(data, product):
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
        _extract_variations_json(sku_mod, product)

    return product


def _extract_variations_json(obj, product):
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


def _scrape_variations_dom(page):
    variations = []
    els = []
    for sel in ["[class*='sku-item']", "[class*='skuItem']",
                 "[class*='sku-property-item']", "[class*='property-item']"]:
        els = page.query_selector_all(sel)
        if els:
            break
    if not els:
        return []

    option_name = "Style"
    for lsel in ["[class*='sku-title']", "[class*='property-title']", "[class*='sku--title']"]:
        lel = page.query_selector(lsel)
        if lel:
            text = lel.inner_text().strip().rstrip(":")
            if text:
                option_name = text
            break

    for el in els:
        var = {"name": "", "price": "", "image": "", "option_name": option_name, "available": True}
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
# WORKER — one browser instance processing its URL chunk
# ═══════════════════════════════════════════════════════════════

def _browser_worker(pw, worker_id, url_chunk, results, results_lock,
                    scraped_ids, total_all, counter, counter_lock):
    """
    One browser instance that scrapes its chunk of URLs then dies.
    Thread-safe via locks for shared state.
    """
    ua = random.choice(USER_AGENTS)
    vp = _random_viewport()

    try:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            user_agent=ua,
            viewport=vp,
            locale="en-US",
            timezone_id=random.choice(["America/New_York", "Europe/London",
                                        "America/Chicago", "America/Los_Angeles"]),
        )

        local_products = []
        local_success = 0
        local_fail = 0

        for url in url_chunk:
            pid = _extract_product_id(url)

            # Skip already-scraped
            with results_lock:
                if pid and pid in scraped_ids:
                    continue

            try:
                product = _scrape_page(context, url)
                if product and product.get("product_title"):
                    local_products.append(product)
                    local_success += 1
                    with results_lock:
                        scraped_ids.add(pid)
                else:
                    local_fail += 1
            except Exception:
                local_fail += 1

            # Update global counter for progress
            with counter_lock:
                counter[0] += 1
                done = counter[0]
                if done % 5 == 0 or done == total_all:
                    with results_lock:
                        total_ok = len(results) + sum(
                            len(r) for r in [local_products])
                    print(f"  [{done}/{total_all}] ~{total_ok} OK — "
                          f"Browser {worker_id}: {local_success} OK, {local_fail} fail")

        context.close()
        browser.close()

        # Merge results
        with results_lock:
            results.extend(local_products)

    except Exception as e:
        print(f"  Browser {worker_id} crashed: {str(e)[:80]}")


# ═══════════════════════════════════════════════════════════════
# ORCHESTRATOR — parallel browser cycles
# ═══════════════════════════════════════════════════════════════

def scrape_urls(urls_file, output_csv="scraped_products.csv", limit=None):
    """
    Scrape AliExpress URLs using 3 parallel browsers.
    Each browser processes 25 URLs then dies and respawns fresh.
    75 URLs per cycle, 15s cooldown between cycles.
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
    scraped_ids, products = _load_checkpoint()

    # Filter out already-scraped
    remaining = [u for u in urls if _extract_product_id(u) not in scraped_ids]

    total = len(urls)
    already = total - len(remaining)
    urls_per_cycle = BROWSERS * URLS_PER_BROWSER  # 75

    print(f"  {total} total URLs, {already} already scraped, {len(remaining)} remaining")
    print(f"  Strategy: {BROWSERS} browsers × {URLS_PER_BROWSER} URLs = "
          f"{urls_per_cycle}/cycle, {COOLDOWN}s cooldown")
    print(f"  Estimated: {len(remaining) // urls_per_cycle + 1} cycles, "
          f"~{(len(remaining) // urls_per_cycle + 1) * 3:.0f} minutes\n")

    start = time.time()
    counter = [already]  # mutable counter for threads
    counter_lock = threading.Lock()
    results_lock = threading.Lock()

    with sync_playwright() as pw:
        # Process in cycles of 75 URLs
        for cycle_start in range(0, len(remaining), urls_per_cycle):
            cycle_urls = remaining[cycle_start:cycle_start + urls_per_cycle]
            cycle_num = cycle_start // urls_per_cycle + 1
            total_cycles = len(remaining) // urls_per_cycle + 1

            print(f"\n  ── Cycle {cycle_num}/{total_cycles}: "
                  f"{len(cycle_urls)} URLs across {BROWSERS} browsers ──")

            # Split URLs across browsers
            chunks = []
            for i in range(BROWSERS):
                chunk = cycle_urls[i * URLS_PER_BROWSER:(i + 1) * URLS_PER_BROWSER]
                if chunk:
                    chunks.append(chunk)

            # Launch browsers in parallel threads
            threads = []
            for i, chunk in enumerate(chunks):
                t = threading.Thread(
                    target=_browser_worker,
                    args=(pw, i + 1, chunk, products, results_lock,
                          scraped_ids, total, counter, counter_lock),
                )
                threads.append(t)
                t.start()

            # Wait for all browsers to finish
            for t in threads:
                t.join()

            # Checkpoint after each cycle
            _save_checkpoint(scraped_ids, products)
            print(f"  Checkpoint saved: {len(products)} products")

            # Cooldown between cycles (skip after last)
            if cycle_start + urls_per_cycle < len(remaining):
                print(f"  Cooling down {COOLDOWN}s before next cycle...")
                time.sleep(COOLDOWN)

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
        successful_ids = {p.get("id") for p in products if p.get("id")}
        failed = [u for u in urls if _extract_product_id(u) not in successful_ids]

        failed_file = output_csv.replace(".csv", "_failed.txt")
        if failed:
            with open(failed_file, "w") as f:
                for u in failed:
                    f.write(u + "\n")

        print(f"\n  {'='*55}")
        print(f"  Scraped:       {len(products)} products")
        print(f"  Failed:        {len(failed)} URLs → {failed_file}")
        print(f"  With variants: {var_products} products ({total_vars} total variants)")
        print(f"  Time:          {elapsed:.0f}s ({elapsed/60:.1f} min)")
        print(f"  Speed:         {len(products)/max(elapsed,1)*60:.0f} products/min")
        print(f"  Output:        {output_csv}")
        print(f"  {'='*55}")

        _clear_checkpoint()
    else:
        print("\n  No products scraped.")
        with open("failed_urls.txt", "w") as f:
            for u in urls:
                f.write(u + "\n")
        print(f"  All {len(urls)} URLs saved to failed_urls.txt")

    return products
