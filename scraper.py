"""
CastForge AliExpress Scraper

3 parallel browser contexts on one browser, async Playwright.
Each context processes 25 URLs then dies and respawns fresh.
75 URLs per cycle, 15s cooldown between cycles.
~1,500 URLs in ~55 minutes.

Usage:
    cd ~/CastForge && python3 main.py scrape links_part2.txt
    cd ~/CastForge && python3 main.py scrape links_part2.txt --limit 150
"""

import asyncio
import csv
import json
import os
import random
import re
import sys
import time
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

CONTEXTS = 3              # Parallel browser contexts
URLS_PER_CONTEXT = 25     # URLs before context dies and respawns
MIN_DELAY = 3.0
MAX_DELAY = 6.0
COOLDOWN = 15             # Seconds between cycles

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


def _fix_ali_image_url(src):
    """Fix AliExpress image URL: correct CDN, strip thumbnail/avif suffix, full-size."""
    url = src
    # Convert aliexpress-media CDN to alicdn
    url = re.sub(r"https?://ae-pic-a1\.aliexpress-media\.com/kf/",
                 "https://ae01.alicdn.com/kf/", url)
    # Strip everything after the base image extension:
    # .jpg_960x960q75.jpg_.avif → .jpg
    # .jpg_350x350.jpg → .jpg
    # .png_480x480.png → .png
    # .jpeg_120x120.jpeg_.webp → .jpeg
    url = re.sub(r"(\.\w{3,4})_[^/]+$", r"\1", url)
    # Strip bare _NNNxNNN suffix
    url = re.sub(r"_\d+x\d+\w*$", "", url)
    # Ensure https
    if url.startswith("//"):
        url = f"https:{url}"
    return url


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

def _load_checkpoint():
    if CHECKPOINT_FILE.exists():
        data = json.loads(CHECKPOINT_FILE.read_text())
        return set(data.get("scraped_ids", [])), data.get("products", [])
    return set(), []


def _save_checkpoint(scraped_ids, products):
    CHECKPOINT_FILE.write_text(json.dumps({
        "scraped_ids": list(scraped_ids),
        "products": products,
    }, ensure_ascii=False))


def _clear_checkpoint():
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()


# ═══════════════════════════════════════════════════════════════
# ASYNC PAGE SCRAPER
# ═══════════════════════════════════════════════════════════════

async def _scrape_page_async(context, url, debug=False):
    """Scrape one AliExpress product page (async Playwright)."""
    product_id = _extract_product_id(url)
    if not product_id:
        return None

    page = await context.new_page()
    await page.add_init_script(STEALTH_JS)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)

        # Wait for price element to render (AliExpress loads prices async)
        try:
            await page.wait_for_selector("[class*='price'], [class*='Price']",
                                          timeout=8000)
        except Exception:
            pass  # Continue even if price doesn't appear

        await page.wait_for_timeout(int(random.uniform(MIN_DELAY, MAX_DELAY) * 1000))

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

        html = await page.content()
        if debug:
            print(f"\n{'='*60}")
            print(f"[DEBUG] URL: {url}")
            print(f"[DEBUG] Page length: {len(html)} chars")
            print(f"[DEBUG] Page title: {(await page.title())[:80]}")

        # ── Embedded JSON extraction ──
        json_product = _extract_from_embedded_json(html, url, product_id, debug=debug)
        if json_product and json_product.get("product_title"):
            if json_product.get("product_images"):
                if debug:
                    print(f"[DEBUG] JSON got title + images → returning")
                return json_product
            product = json_product
            if debug:
                print(f"[DEBUG] JSON got title but NO images → falling through to DOM")

        # ── DOM: Title ──
        if not product.get("product_title"):
            for sel in ["h1[data-pl='product-title']", "h1.product-title-text",
                         "[class*='title--wrap'] h1", "h1"]:
                el = await page.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if debug:
                        print(f"[DEBUG] Title '{sel}': '{text[:60]}'")
                    if len(text) > 5:
                        product["product_title"] = text
                        break
                elif debug:
                    print(f"[DEBUG] Title '{sel}': NOT FOUND")

        # ── DOM: Price ──
        if not product.get("product_price"):
            for sel in ["[class*='price--current'] span",
                         "[class*='es--wrap--erdmPRe'] span",
                         "[class*='uniform-banner-box'] span[class*='es--wrap']",
                         "[class*='Price'] [class*='current'] span",
                         "[class*='Price_price__'] span",
                         "[class*='product-price-value']"]:
                el = await page.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if debug:
                        print(f"[DEBUG] Price '{sel}': '{text}'")
                    if text and re.search(r"[\d.]+", text):
                        product["product_price"] = text
                        break
                elif debug:
                    print(f"[DEBUG] Price '{sel}': NOT FOUND")

            # Last resort: any element with price-like class
            if not product.get("product_price"):
                for sel in ["[class*='price']", "[class*='Price']"]:
                    el = await page.query_selector(sel)
                    if el:
                        all_text = (await el.inner_text()).strip()
                        if debug:
                            print(f"[DEBUG] Price fallback '{sel}': '{all_text[:80]}'")
                        # Handle both regular £ and full-width ￡ (U+FFE1)
                        m = re.search(r"[\£\$€\uffe1]\s*([\d.]+)", all_text)
                        if m:
                            product["product_price"] = m.group()
                            break
                            break

        # ── DOM: Images ──
        # Product images are .jpg from alicdn.com/kf/S*.jpg (always start with S)
        # Reject: icons, store logos, dimension-suffixed paths, non-jpg
        if not product.get("product_images"):
            images = []
            seen_hashes = set()

            all_imgs = await page.query_selector_all("img")
            if debug:
                print(f"[DEBUG] Total <img> tags on page: {len(all_imgs)}")

            for img_el in all_imgs:
                for attr in ["src", "data-src"]:
                    val = (await img_el.get_attribute(attr)) or ""
                    if not val:
                        continue

                    full = _fix_ali_image_url(val)
                    if not full.startswith("http"):
                        full = f"https:{full}"

                    # MUST be alicdn.com/kf/S (product images always start with S)
                    if not re.search(r"alicdn\.com/kf/S", full):
                        continue
                    # MUST end in .jpg or .jpeg
                    if not re.search(r"\.(jpg|jpeg)$", full, re.IGNORECASE):
                        continue
                    # REJECT dimension patterns in path like /27x27/ or /48x48/
                    if re.search(r"/\d+x\d+", full):
                        continue

                    # Deduplicate by filename hash (the S... part)
                    m = re.search(r"/kf/(S[^/.]+)", full)
                    img_hash = m.group(1) if m else full
                    if img_hash in seen_hashes:
                        continue
                    seen_hashes.add(img_hash)

                    images.append(full)
                    if debug:
                        print(f"  [DEBUG] KEEP: {full[:80]}")

            if images:
                product["product_image"] = images[0]
                product["product_images"] = "|".join(images)
            if debug:
                print(f"[DEBUG] Product images: {len(images)}")

        # ── DOM: Shipping ──
        # Search broadly for "free shipping" text in shipping/delivery elements
        ship_found = False
        for sel in ["[class*='shipping']", "[class*='delivery']",
                     "[class*='dynamic-shipping']"]:
            els = await page.query_selector_all(sel)
            for el in els:
                text = (await el.inner_text()).strip().lower()
                if debug:
                    print(f"[DEBUG] Shipping '{sel}': '{text[:80]}'")
                if "free shipping" in text or "free delivery" in text:
                    product["shipping"] = "0"
                    ship_found = True
                    break
                # Check for a shipping cost
                m = re.search(r"[\£\$€\uffe1]\s*([\d.]+)", text)
                if m and "shipping" in text:
                    product["shipping"] = m.group(1)
                    ship_found = True
                    break
            if ship_found:
                break

        # ── DOM: Store + Sales ──
        for sel in ["[class*='store-name'] a", "a[class*='store--name']",
                     "[class*='shop-name'] a"]:
            el = await page.query_selector(sel)
            if el:
                product["store_name"] = (await el.inner_text()).strip()
                break

        for sel in ["[class*='reviewer--sold']", "span[class*='count--trade']",
                     "[class*='trade-count']"]:
            el = await page.query_selector(sel)
            if el:
                product["total_sales"] = (await el.inner_text()).strip()
                product["trade_info"] = product["total_sales"]
                break

        # ── DOM: Variations ──
        variations = await _scrape_variations_dom(page)
        if variations:
            product["variations"] = json.dumps(variations, ensure_ascii=False)
            var_imgs = {v["name"]: v["image"] for v in variations if v.get("image")}
            if var_imgs:
                product["variation_images"] = json.dumps(var_imgs, ensure_ascii=False)

        if debug:
            print(f"\n[DEBUG] FINAL RESULT:")
            print(f"  title:      {product['product_title'][:60]}")
            print(f"  price:      {product['product_price']}")
            print(f"  shipping:   {product['shipping']}")
            print(f"  images:     {len(product['product_images'].split('|')) if product['product_images'] else 0}")
            if product['product_images']:
                for i, img in enumerate(product['product_images'].split('|')[:3]):
                    print(f"    [{i+1}] {img[:80]}")
            print(f"  store:      {product['store_name']}")
            print(f"  variations: {len(json.loads(product['variations'])) if product['variations'] else 0}")
            print(f"{'='*60}\n")

        return product if product.get("product_title") else None

    except Exception as e:
        if debug:
            import traceback
            print(f"[DEBUG] EXCEPTION: {e}")
            traceback.print_exc()
        return None
    finally:
        await page.close()


async def _scrape_variations_dom(page):
    variations = []
    els = []
    for sel in ["[class*='sku-item']", "[class*='skuItem']",
                 "[class*='sku-property-item']", "[class*='property-item']"]:
        els = await page.query_selector_all(sel)
        if els:
            break
    if not els:
        return []

    option_name = "Style"
    for lsel in ["[class*='sku-title']", "[class*='property-title']", "[class*='sku--title']"]:
        lel = await page.query_selector(lsel)
        if lel:
            text = (await lel.inner_text()).strip().rstrip(":")
            if text:
                option_name = text
            break

    for el in els:
        var = {"name": "", "price": "", "image": "", "option_name": option_name, "available": True}
        var["name"] = (await el.get_attribute("title")) or (await el.inner_text()).strip()
        img_el = await el.query_selector("img")
        if img_el:
            src = (await img_el.get_attribute("src")) or ""
            if src and ("alicdn" in src or "ae01" in src):
                full = re.sub(r"_\d+x\d+\.\w+$", ".jpg", src)
                var["image"] = full if full.startswith("http") else f"https:{full}"
        classes = (await el.get_attribute("class")) or ""
        if "disabled" in classes or "unavailable" in classes:
            var["available"] = False
        if var["name"]:
            variations.append(var)
    return variations


# ═══════════════════════════════════════════════════════════════
# JSON EXTRACTION (sync — operates on strings, no Playwright)
# ═══════════════════════════════════════════════════════════════

def _extract_from_embedded_json(html, url, product_id, debug=False):
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

    # Strategy 1: __INIT_DATA__
    m = re.search(r'window\.__INIT_DATA__\s*=\s*(\{.+?\})\s*;?\s*</script>', html, re.DOTALL)
    if m:
        if debug:
            print(f"[DEBUG] Found __INIT_DATA__ ({len(m.group(1))} chars)")
        try:
            data = json.loads(m.group(1))
            if debug:
                print(f"[DEBUG] JSON parsed OK, top keys: {list(data.keys())[:5]}")
            _deep_extract(data, product)
            if debug:
                print(f"[DEBUG] After deep_extract: title='{product['product_title'][:40]}' "
                      f"price='{product['product_price']}' "
                      f"images={len(product['product_images'].split('|')) if product['product_images'] else 0}")
            if product.get("product_title"):
                return product
        except (json.JSONDecodeError, KeyError) as e:
            if debug:
                print(f"[DEBUG] JSON parse error: {e}")
    elif debug:
        print(f"[DEBUG] No __INIT_DATA__ found")

    # Strategy 2: actionModule
    m = re.search(r'data:\s*(\{"actionModule".+?\})\s*[,;}\n]', html, re.DOTALL)
    if m:
        if debug:
            print(f"[DEBUG] Found actionModule data")
        try:
            data = json.loads(m.group(1))
            _extract_from_run_params(data, product)
            if product.get("product_title"):
                return product
        except (json.JSONDecodeError, KeyError) as e:
            if debug:
                print(f"[DEBUG] actionModule parse error: {e}")
    elif debug:
        print(f"[DEBUG] No actionModule found")

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
                    u = _fix_ali_image_url(u)
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
        full = [_fix_ali_image_url(i if i.startswith("http") else f"https:{i}") for i in imgs]
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
                var["image"] = _fix_ali_image_url(img if img.startswith("http") else f"https:{img}")
            if var["name"]:
                variations.append(var)
    if variations:
        product["variations"] = json.dumps(variations, ensure_ascii=False)
        var_imgs = {v["name"]: v["image"] for v in variations if v.get("image")}
        if var_imgs:
            product["variation_images"] = json.dumps(var_imgs, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# CONTEXT WORKER — one context processing its URL chunk
# ═══════════════════════════════════════════════════════════════

async def _context_worker(browser, worker_id, url_chunk, scraped_ids,
                           progress, debug=False):
    """
    One browser context that scrapes its chunk of URLs.
    Returns list of scraped products.
    """
    ua = random.choice(USER_AGENTS)
    vp = _random_viewport()
    tz = random.choice(["America/New_York", "Europe/London",
                         "America/Chicago", "America/Los_Angeles"])

    context = await browser.new_context(
        user_agent=ua, viewport=vp, locale="en-US", timezone_id=tz,
    )

    local_products = []

    for url in url_chunk:
        pid = _extract_product_id(url)
        if pid and pid in scraped_ids:
            progress["skip"] += 1
            continue

        try:
            product = await _scrape_page_async(context, url, debug=debug)
            if product and product.get("product_title"):
                local_products.append(product)
                scraped_ids.add(pid)
                progress["ok"] += 1
            else:
                progress["fail"] += 1
        except Exception:
            progress["fail"] += 1

        done = progress["ok"] + progress["fail"] + progress["skip"]
        total = progress["total"]
        if done % 5 == 0:
            print(f"  [{done}/{total}] {progress['ok']} OK, "
                  f"{progress['fail']} fail — Ctx {worker_id}")

    await context.close()
    return local_products


# ═══════════════════════════════════════════════════════════════
# ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════

async def _run_scraper(urls, scraped_ids, products, debug=False):
    """Main async scraper loop with rotating contexts."""
    from playwright.async_api import async_playwright

    remaining = [u for u in urls if _extract_product_id(u) not in scraped_ids]
    total = len(urls)
    already = total - len(remaining)
    urls_per_cycle = CONTEXTS * URLS_PER_CONTEXT  # 75

    print(f"  {total} total URLs, {already} already scraped, "
          f"{len(remaining)} remaining")
    print(f"  Strategy: {CONTEXTS} contexts × {URLS_PER_CONTEXT} URLs = "
          f"{urls_per_cycle}/cycle, {COOLDOWN}s cooldown")
    num_cycles = (len(remaining) + urls_per_cycle - 1) // urls_per_cycle
    print(f"  Estimated: {num_cycles} cycles, ~{num_cycles * 3:.0f} minutes\n")

    progress = {"ok": 0, "fail": 0, "skip": already, "total": total}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )

        for cycle_start in range(0, len(remaining), urls_per_cycle):
            cycle_urls = remaining[cycle_start:cycle_start + urls_per_cycle]
            cycle_num = cycle_start // urls_per_cycle + 1

            print(f"\n  ── Cycle {cycle_num}/{num_cycles}: "
                  f"{len(cycle_urls)} URLs across {CONTEXTS} contexts ──")

            # Split URLs across contexts
            chunks = []
            for i in range(CONTEXTS):
                chunk = cycle_urls[i * URLS_PER_CONTEXT:(i + 1) * URLS_PER_CONTEXT]
                if chunk:
                    chunks.append(chunk)

            # Run all contexts concurrently with asyncio.gather
            tasks = [
                _context_worker(browser, i + 1, chunk, scraped_ids, progress, debug=debug)
                for i, chunk in enumerate(chunks)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Collect products from all contexts
            for result in results:
                if isinstance(result, list):
                    products.extend(result)
                elif isinstance(result, Exception):
                    print(f"  Context error: {result}")

            # Checkpoint
            _save_checkpoint(scraped_ids, products)
            print(f"  Checkpoint: {len(products)} products saved")

            # Cooldown (skip after last cycle)
            if cycle_start + urls_per_cycle < len(remaining):
                print(f"  Cooling down {COOLDOWN}s...")
                await asyncio.sleep(COOLDOWN)

        await browser.close()

    return products


# ═══════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════

def scrape_urls(urls_file, output_csv="scraped_products.csv", limit=None, debug=False):
    """
    Scrape AliExpress URLs using 3 parallel browser contexts.
    Each context processes 25 URLs then dies and respawns fresh.
    75 URLs per cycle, 15s cooldown between cycles.
    """
    with open(urls_file) as f:
        urls = [line.strip() for line in f
                if line.strip() and not line.startswith("#")]

    if limit:
        urls = urls[:limit]

    scraped_ids, products = _load_checkpoint()

    start = time.time()
    products = asyncio.run(_run_scraper(urls, scraped_ids, products, debug=debug))
    elapsed = time.time() - start

    # Write CSV
    if products:
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES,
                                     extrasaction="ignore")
            writer.writeheader()
            for prod in products:
                writer.writerow(prod)

        var_products = sum(1 for p in products if p.get("variations"))
        total_vars = sum(
            len(json.loads(p.get("variations", "[]") or "[]"))
            for p in products if p.get("variations")
        )

        successful_ids = {p.get("id") for p in products if p.get("id")}
        failed = [u for u in urls
                  if _extract_product_id(u) not in successful_ids]
        failed_file = output_csv.replace(".csv", "_failed.txt")
        if failed:
            with open(failed_file, "w") as f:
                for u in failed:
                    f.write(u + "\n")

        print(f"\n  {'='*55}")
        print(f"  Scraped:       {len(products)} products")
        print(f"  Failed:        {len(failed)} URLs → {failed_file}")
        print(f"  With variants: {var_products} ({total_vars} total variants)")
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
        print(f"  All {len(urls)} URLs → failed_urls.txt")

    return products
