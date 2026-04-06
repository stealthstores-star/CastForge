#!/usr/bin/env python3
"""
CastForge Shopify Fixer — fix AutoDS-imported products.
Matches by title to ai_title_cache.json, fixes stock/title/category/images/description/status.

Usage:
    python3 shopify_fixer.py test        # Fix 10 products, show results
    python3 shopify_fixer.py run         # Fix all products, resumable
    python3 shopify_fixer.py run --poll   # Fix all + poll every 10min for new imports
"""
import json, os, re, sys, time, unicodedata
from pathlib import Path

import requests
import config
from categorizer import categorize, clean_title

# ── Files ──
AI_CACHE_FILE = Path("ai_title_cache.json")
CHECKPOINT_FILE = Path("scrape_checkpoint.json")
COLLECTION_MAP_FILE = Path("collection_map.json")
PROGRESS_FILE = Path("shopify_fix_progress.json")
PUSHED_TITLES_FILE = Path("pushed_titles.json")
DELETED_FILE = Path("deleted_no_images.json")
UNMATCHED_FILE = Path("unmatched_products.json")
ERRORS_FILE = Path("shopify_fix_errors.json")

# ── Shopify API ──
def get_token():
    from uploader import get_shopify_token
    return get_shopify_token()

def shopify_headers(token):
    return {"Content-Type": "application/json", "X-Shopify-Access-Token": token}

def shopify_base():
    return f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

# ── Normalisation ──
def _strip_ali_suffix(text):
    """Remove ' - AliExpress' and ' - AliExpress NN' suffixes."""
    return re.sub(r"\s*-\s*AliExpress\s*\d*\s*$", "", text, flags=re.IGNORECASE)

def normalise(text):
    """Lowercase, strip emojis/punctuation/quotes/empty parens/extra whitespace."""
    if not text:
        return ""
    text = _strip_ali_suffix(text)
    # Remove emojis and special unicode
    text = "".join(c for c in text if unicodedata.category(c)[0] not in ("So", "Sk", "Sm"))
    # Remove all quote characters: " ' " " ' ' « » etc
    text = re.sub(r'["\'\u201c\u201d\u2018\u2019\u00ab\u00bb\u300c\u300d`]', ' ', text)
    # Remove punctuation except hyphens and slashes (preserve scales like 1/35)
    text = re.sub(r"[^\w\s/\-]", " ", text)
    # Remove empty parentheses: () or ( )
    text = re.sub(r"\(\s*\)", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text

# ── Load local data ──
def load_ai_cache():
    if AI_CACHE_FILE.exists():
        return json.loads(AI_CACHE_FILE.read_text())
    print("  ERROR: ai_title_cache.json not found")
    return {}

def load_scrape_data():
    """Load scrape checkpoint, index by product_title for image lookup."""
    if not CHECKPOINT_FILE.exists():
        return {}
    data = json.loads(CHECKPOINT_FILE.read_text())
    by_title = {}
    for p in data.get("products", []):
        title = p.get("product_title", "")
        if title:
            by_title[title] = p
            by_title[normalise(title)] = p
    return by_title

def load_collection_map():
    if COLLECTION_MAP_FILE.exists():
        return json.loads(COLLECTION_MAP_FILE.read_text())
    return {}

def load_progress():
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {"processed_ids": [], "matched": 0, "unmatched": 0, "errors": 0}

def save_progress(progress):
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2))

def load_pushed_titles():
    """Load {product_id: {title, raw_title, timestamp}} from pushed_titles.json."""
    if PUSHED_TITLES_FILE.exists():
        return json.loads(PUSHED_TITLES_FILE.read_text())
    return {}

def save_pushed_title(pid, title, raw_title):
    """Append a pushed title immediately to pushed_titles.json."""
    data = load_pushed_titles()
    data[str(pid)] = {"title": title, "raw_title": raw_title, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
    PUSHED_TITLES_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

# ── Fetch all Shopify products ──
def fetch_all_products(token, fields="id,title,status,tags,images,variants"):
    """Paginate through all Shopify products."""
    headers = shopify_headers(token)
    products = []
    url = f"{shopify_base()}/products.json?limit=250&fields={fields}&status=draft"
    while url:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 2)))
            continue
        if r.status_code != 200:
            print(f"  API error {r.status_code}: {r.text[:200]}")
            break
        products.extend(r.json().get("products", []))
        if len(products) % 1000 < 250:
            print(f"    ...{len(products)} fetched", flush=True)
        # Pagination
        url = None
        link = r.headers.get("Link", "")
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.split("<")[1].split(">")[0]
        time.sleep(0.5)
    return products

# ── Match Shopify product to AI cache ──
STOPWORDS = {"resin", "scale", "model", "kit", "gk", "cast", "figure", "figures",
             "miniature", "statue", "bust", "diorama", "unpainted", "unassembled",
             "new", "hot", "sale", "free", "shipping", "quality", "high", "the",
             "and", "for", "with", "from", "set", "pcs", "piece", "pieces",
             "aliexpress"}

def _tokenise(text):
    """Split into lowercase content tokens, exclude stopwords. Strip leading punct from each token."""
    text = normalise(text)
    tokens = set()
    for w in re.split(r"[\s/\-]+", text):
        w = re.sub(r"^[^\w]+", "", w)  # strip leading punct (& → , . → etc)
        if len(w) < 2:
            continue
        if w in STOPWORDS:
            continue
        if re.match(r"^\d+$", w) and len(w) < 4:
            continue
        tokens.add(w)
    return tokens

def match_product(shopify_title, ai_cache, cache_normalised, cache_tokens=None,
                  shopify_images=None, scrape_data=None):
    """Match by exact → normalised → subset coverage → Jaccard fallback → image-ID."""
    # 1. Exact match
    if shopify_title in ai_cache:
        return shopify_title, ai_cache[shopify_title], "exact"

    # 2. Normalised match
    norm = normalise(shopify_title)
    if norm in cache_normalised:
        raw = cache_normalised[norm]
        return raw, ai_cache[raw], "normalised"

    # 3. Bidirectional subset coverage: either direction ≥85%, ≥5 shared
    if cache_tokens:
        shop_tokens = _tokenise(shopify_title)
        if shop_tokens:
            best_score, best_shared, best_raw, best_dir = 0.0, 0, None, ""

            for raw_title, raw_tokens in cache_tokens.items():
                if not raw_tokens:
                    continue
                inter = shop_tokens & raw_tokens
                shared = len(inter)
                if shared < 5:
                    continue
                fwd = shared / len(shop_tokens)   # % of Shopify tokens in cache
                rev = shared / len(raw_tokens)     # % of cache tokens in Shopify
                best_dir_score = max(fwd, rev)
                direction = f"fwd({fwd:.0%})" if fwd >= rev else f"rev({rev:.0%})"

                if best_dir_score >= 0.85 and best_dir_score > best_score:
                    best_score, best_shared, best_raw, best_dir = best_dir_score, shared, raw_title, direction

            if best_raw:
                return best_raw, ai_cache[best_raw], f"subset-{best_dir},{best_shared}"

    # 4. Image-ID match: extract AliExpress product ID from alicdn.com image URLs
    if shopify_images and scrape_data:
        for img in shopify_images:
            src = img.get("src", "") if isinstance(img, dict) else str(img)
            for m in re.finditer(r'/(\d{10,})[\./]', src):
                pid = m.group(1)
                for raw_title, p in scrape_data.items():
                    if isinstance(p, dict) and p.get("id") == pid:
                        if raw_title in ai_cache:
                            return raw_title, ai_cache[raw_title], "image_id"

    return None

def _download_with_retry(url, timeout=20, retries=3):
    """Download URL with exponential backoff. Returns response or None."""
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                         "Referer": "https://www.aliexpress.com/"})
            if r.status_code == 200:
                return r
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(2 ** (attempt + 1))  # 2, 4, 8
    return None

# ── Vision classify images using Haiku 4.5 ──
def _resize_for_vision(url):
    """Download image, resize to 512x512 IN MEMORY ONLY, return base64. Original URL untouched."""
    try:
        r = _download_with_retry(url, timeout=15)
        if not r:
            return None
        from PIL import Image
        from io import BytesIO
        import base64
        img = Image.open(BytesIO(r.content))
        img = img.convert("RGB")
        img.thumbnail((512, 512))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return base64.standard_b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return None

def classify_images(image_urls, api_key):
    """Binary YES/NO classification per image. Returns list of (url, 'YES'|'NO')."""
    if not image_urls:
        return []

    results = []
    for url in image_urls:
        b64 = _resize_for_vision(url)
        if not b64:
            results.append((url, "NO"))
            continue
        try:
            r = requests.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-haiku-4-5-20251001", "max_tokens": 10,
                      "messages": [{"role": "user", "content": [
                          {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                          {"type": "text", "text": "Reply YES if image shows a physical product clearly visible AND any watermarks/text take up less than 25% of the image area. Reply NO if the image has large prominent watermark text overlaid across the main product (e.g. store brand name repeated diagonally, giant logos covering the product), or is >50% pure text, pure logo, blank/empty, or pure size chart grid. Small corner watermarks are fine. When the product itself is the dominant visual element, reply YES. ONE word only: YES or NO."}
                      ]}]},
                timeout=30)
            if r.status_code == 200:
                answer = r.json()["content"][0]["text"].strip().upper()
                results.append((url, "YES" if "YES" in answer else "NO"))
            else:
                results.append((url, "YES"))  # keep on API error
        except Exception:
            results.append((url, "YES"))
        time.sleep(0.3)

    return results

# ── Generate AI title via vision ──
def generate_ai_title(image_urls, fallback_title, api_key):
    """Generate clean product title from first 1-2 product images using Haiku vision."""
    content = []
    for url in image_urls[:2]:
        b64 = _resize_for_vision(url)
        if b64:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})

    if not content:
        return fallback_title

    content.append({"type": "text", "text": f"""Look at this product image. Write an SEO-friendly e-commerce title (60-90 chars) for a resin model/miniature store. Include in this order: (1) specific subject with identifying details (e.g. 'Roman Legionary Centurion', 'WWII German Tiger I Tank Commander', 'Cyberpunk Assassin with Katana'), (2) scale if visible, (3) material ('Resin'), (4) type ('Figure', 'Bust', 'Kit', 'Diorama'). Be specific — 'Viking Warrior' not 'Warrior', 'Spitfire Mk.IX' not 'WWII Aircraft'. The original listing title was: {fallback_title[:120]}. Reply with ONLY the title."""})

    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 100,
                  "messages": [{"role": "user", "content": content}]},
            timeout=30)
        if r.status_code == 200:
            title = r.json()["content"][0]["text"].strip().strip('"').strip("'")
            if 10 < len(title) < 100:
                return title
    except Exception:
        pass
    return fallback_title

# ── Generate description ──
def generate_description(title, category, api_key):
    """Generate ~120 word SEO product description using Haiku."""
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 400,
                  "messages": [{"role": "user", "content": f"""Write a product description for {title}. Category: {category}. Format as HTML with:
Opening sentence hooking the buyer (what makes this product special)
<ul><li> bulleted key features (4-5 bullets: scale, material, subject details, assembly required, recommended use)
Closing paragraph (who this is for, shipping mention)
Use <p>, <ul>, <li>, <strong> tags only. No code fences. No generic filler like 'elevate your collection' or 'perfect for enthusiasts'. Reference specific details from the title. 100-140 words total."""}]},
            timeout=30)
        if r.status_code == 200:
            desc = r.json()["content"][0]["text"].strip()
            desc = re.sub(r"^```html?\s*\n?", "", desc)
            desc = re.sub(r"\n?```\s*$", "", desc)
            return desc.strip()
    except Exception:
        pass
    return f"<p>Premium quality {title}. High-detail resin model kit requiring assembly and painting. Perfect for collectors and hobbyists.</p>"

# ── Update a single Shopify product ──
def fix_product(product, ai_title, category_handle, parent_handle, description,
                good_images, token, collection_map, location_id=None, test_mode=False):
    """Apply all fixes to a Shopify product."""
    headers = shopify_headers(token)
    base = shopify_base()
    pid = product["id"]
    errors = []

    # 1. Build update payload
    update = {"product": {"id": pid}}

    # Title
    update["product"]["title"] = ai_title

    # Description
    update["product"]["body_html"] = description

    # Status → active
    update["product"]["status"] = "active"

    # Tags — preserve existing, add category
    existing_tags = product.get("tags", "") or ""
    tag_list = [t.strip() for t in existing_tags.split(",") if t.strip()]
    if category_handle and category_handle not in tag_list:
        tag_list.append(category_handle)
    if parent_handle and parent_handle not in tag_list:
        tag_list.append(parent_handle)
    update["product"]["tags"] = ", ".join(tag_list)

    # 2. Update product (title, description, status, tags)
    try:
        r = requests.put(f"{base}/products/{pid}.json", headers=headers,
                        json=update, timeout=30)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 2)))
            r = requests.put(f"{base}/products/{pid}.json", headers=headers,
                            json=update, timeout=30)
        if r.status_code not in (200, 201):
            errors.append(f"Update failed: {r.status_code} {r.text[:100]}")
    except Exception as e:
        errors.append(f"Update error: {e}")
    time.sleep(0.5)

    # 3. Set inventory to 10 for all variants
    loc_id = location_id
    if test_mode:
        print(f"       INV location_id={loc_id}")
    if loc_id:
        for variant in product.get("variants", []):
            iid = variant.get("inventory_item_id")
            vid = variant.get("id")
            if not iid:
                if test_mode:
                    print(f"       INV variant={vid}: NO inventory_item_id, skipping")
                continue
            try:
                # Enable tracking first
                track_r = requests.put(f"{base}/inventory_items/{iid}.json", headers=headers,
                           json={"inventory_item": {"id": iid, "tracked": True}},
                           timeout=15)
                if test_mode:
                    print(f"       INV TRACK iid={iid}: {track_r.status_code} {track_r.text[:120]}")
                time.sleep(0.3)
                # Set available quantity to 10
                inv_payload = {"location_id": loc_id, "inventory_item_id": iid, "available": 10}
                if test_mode:
                    print(f"       INV SET request: {json.dumps(inv_payload)}")
                ir = requests.post(f"{base}/inventory_levels/set.json", headers=headers,
                                 json=inv_payload, timeout=15)
                if test_mode:
                    print(f"       INV SET response: {ir.status_code} {ir.text[:200]}")
                if ir.status_code not in (200, 201):
                    errors.append(f"Inventory set failed variant={vid}: {ir.status_code} {ir.text[:100]}")
            except Exception as e:
                errors.append(f"Inventory error variant={vid}: {e}")
            time.sleep(0.3)
    elif test_mode:
        print(f"       INV ERROR: no location_id found")

    # Verify inventory after setting (test mode only)
    if test_mode and loc_id:
        time.sleep(1)
        try:
            vr = requests.get(f"{base}/products/{pid}.json?fields=id,variants", headers=headers, timeout=15)
            if vr.status_code == 200:
                vdata = vr.json().get("product", {}).get("variants", [])
                for v in vdata:
                    print(f"       INV VERIFY: variant={v.get('id')} inventory_quantity={v.get('inventory_quantity')} tracked={v.get('inventory_management')}")
        except Exception as e:
            print(f"       INV VERIFY ERROR: {e}")

    # 4. Assign to collections
    if category_handle and collection_map:
        for handle in [category_handle, parent_handle]:
            if handle and handle in collection_map:
                try:
                    requests.post(f"{base}/collects.json", headers=headers,
                                json={"collect": {"product_id": pid, "collection_id": collection_map[handle]}},
                                timeout=15)
                except Exception:
                    pass
                time.sleep(0.3)

    return errors

# ── Main ──
def run(test_mode=False, poll=False):
    print("\n══════════════════════════════════════")
    print("  CastForge Shopify Fixer")
    print("══════════════════════════════════════\n")

    # Load data
    ai_cache = load_ai_cache()
    print(f"  AI title cache: {len(ai_cache)} entries")

    scrape_data = load_scrape_data()
    print(f"  Scrape data: {len(scrape_data) // 2} products")

    collection_map = load_collection_map()
    print(f"  Collections: {len(collection_map)}")

    api_key = config.ANTHROPIC_API_KEY
    if not api_key or api_key == "sk-ant-xxx":
        print("  ERROR: ANTHROPIC_API_KEY required for vision + descriptions")
        return

    # Build normalised + token + reverse cache indices
    cache_normalised = {}
    cache_tokens = {}
    ai_title_reverse = {}  # ai_title → raw_title (detect already-processed products)
    for raw_title, ai_title_val in ai_cache.items():
        cache_normalised[normalise(raw_title)] = raw_title
        cache_tokens[raw_title] = _tokenise(raw_title)
        if ai_title_val:
            ai_title_reverse[ai_title_val] = raw_title
            ai_title_reverse[normalise(ai_title_val)] = raw_title

    # Load pushed titles (vision-generated titles from previous runs)
    pushed_titles = load_pushed_titles()
    pushed_title_set = set()  # set of normalised titles we've already pushed
    for pt_data in pushed_titles.values():
        t = pt_data.get("title", "")
        if t:
            pushed_title_set.add(t)
            pushed_title_set.add(normalise(t))
            ai_title_reverse[t] = pt_data.get("raw_title", t)
            ai_title_reverse[normalise(t)] = pt_data.get("raw_title", t)
    print(f"  Reverse AI title index: {len(ai_title_reverse)} entries (inc. {len(pushed_titles)} pushed)")

    token = get_token()

    # Fetch location_id once at startup
    _headers = shopify_headers(token)
    _base = shopify_base()
    location_id = None
    try:
        lr = requests.get(f"{_base}/locations.json", headers=_headers, timeout=15)
        if lr.status_code == 200:
            locations = lr.json().get("locations", [])
            # Prefer non-legacy active location
            for loc in locations:
                if loc.get("active") and not loc.get("legacy"):
                    location_id = loc["id"]
                    break
            # Fallback: first active
            if not location_id:
                for loc in locations:
                    if loc.get("active"):
                        location_id = loc["id"]
                        break
            # Fallback: just first
            if not location_id and locations:
                location_id = locations[0]["id"]
    except Exception as e:
        print(f"  ERROR fetching locations: {e}")
    print(f"  Using location_id={location_id}")
    if not location_id:
        print("  WARNING: no location_id — inventory updates will be skipped")

    progress = load_progress()
    # Fix 3: manually add known-stuck product IDs
    manual_ids = [9208970707197]
    for mid in manual_ids:
        if mid not in progress["processed_ids"]:
            progress["processed_ids"].append(mid)
    processed_set = set(progress["processed_ids"])
    save_progress(progress)

    print(f"  Progress file has {len(processed_set)} IDs")
    if test_mode:
        progress["matched"] = 0
        progress["unmatched"] = 0
        progress["errors"] = 0
    unmatched = []

    while True:
        print(f"\n  Fetching draft products from Shopify...")
        products = fetch_all_products(token)
        print(f"  Found {len(products)} draft products")

        # Filter already processed
        filtered_out = len([p for p in products if p["id"] in processed_set])
        todo = [p for p in products if p["id"] not in processed_set]
        print(f"  Filtered out by progress: {filtered_out}")
        print(f"  To process: {len(todo)}")

        if test_mode:
            # Pick 10 products spanning different scenarios
            with_variants = [p for p in todo if len(p.get("variants", [])) > 1]
            many_images = [p for p in todo if len(p.get("images", [])) > 3]
            no_images = [p for p in todo if len(p.get("images", [])) == 0]
            long_titles = [p for p in todo if len(p.get("title", "")) > 200 or any(ord(c) > 0x2000 for c in p.get("title", ""))]
            selected = []
            for pool, count in [(with_variants, 3), (many_images, 3), (no_images, 2), (long_titles, 2)]:
                for p in pool:
                    if p not in selected and len(selected) < 10:
                        selected.append(p)
                        if len([s for s in selected if s in pool]) >= count:
                            break
            # Fill remaining with random products
            for p in todo:
                if len(selected) >= 10:
                    break
                if p not in selected:
                    selected.append(p)
            todo = selected[:10]
            print(f"  TEST MODE: {len(todo)} products selected:")
            print(f"    with variants: {sum(1 for p in todo if len(p.get('variants',[])) > 1)}")
            print(f"    many images:   {sum(1 for p in todo if len(p.get('images',[])) > 3)}")
            print(f"    no images:     {sum(1 for p in todo if len(p.get('images',[])) == 0)}")
            print(f"    edge titles:   {sum(1 for p in todo if len(p.get('title','')) > 200)}\n")
            test_stats = {"exact": 0, "normalised": 0, "subset": 0, "jaccard": 0, "image_id": 0, "unmatched": 0,
                          "images_kept": 0, "images_deleted": 0, "api_errors": 0}

        if not todo:
            if poll:
                print(f"  No new products. Polling again in 10 minutes...")
                time.sleep(600)
                continue
            else:
                print("  Nothing to process.")
                break

        t0 = time.time()
        delete_count = [0]
        for i, product in enumerate(todo):
            pid = product["id"]
            shopify_title = product.get("title", "")

            # Match
            match = match_product(shopify_title, ai_cache, cache_normalised,
                                  cache_tokens=cache_tokens,
                                  shopify_images=product.get("images", []),
                                  scrape_data=scrape_data)
            if not match:
                # Check if this product's title IS an AI title (already processed in a previous run)
                is_already_done = shopify_title in ai_title_reverse or normalise(shopify_title) in ai_title_reverse
                if is_already_done:
                    # Already processed — skip silently, add to progress
                    processed_set.add(pid)
                    progress["processed_ids"].append(pid)
                    save_progress(progress)
                    if test_mode:
                        print(f"  [{i+1}] ⏭ ALREADY_PROCESSED (title matches AI output): {shopify_title[:60]}")
                    continue

                progress["unmatched"] += 1
                unmatched.append({"id": pid, "title": shopify_title})
                processed_set.add(pid)
                progress["processed_ids"].append(pid)
                save_progress(progress)
                if test_mode:
                    test_stats["unmatched"] += 1
                    # Find closest cache entry for diagnosis
                    shop_tokens = _tokenise(shopify_title)
                    best_score, best_shared, best_raw = 0.0, 0, ""
                    for raw, toks in cache_tokens.items():
                        inter = shop_tokens & toks
                        shared = len(inter)
                        union = shop_tokens | toks
                        score = shared / len(union) if union else 0.0
                        if score > best_score:
                            best_score, best_shared, best_raw = score, shared, raw
                    shop_only = sorted(shop_tokens - _tokenise(best_raw)) if best_raw else []
                    cache_only = sorted(_tokenise(best_raw) - shop_tokens) if best_raw else []
                    print(f"  [{i+1}] ✗ UNMATCHED")
                    print(f"       Shopify: {shopify_title}")
                    print(f"       Closest: {best_raw}")
                    print(f"       Token overlap: {best_score:.0%} | Shared: {best_shared} | Shop-only: {shop_only[:8]} | Cache-only: {cache_only[:8]}")
                continue

            raw_title, cached_title, match_type = match
            if test_mode:
                stat_key = "subset" if match_type.startswith("subset") else "jaccard" if match_type.startswith("jaccard") else match_type
                test_stats[stat_key] = test_stats.get(stat_key, 0) + 1

            # Get images from scrape data
            scrape_product = scrape_data.get(raw_title) or scrape_data.get(normalise(raw_title))
            extra_images = []
            if scrape_product:
                imgs_raw = scrape_product.get("product_images", "")
                if imgs_raw:
                    extra_images = [u.strip() for u in imgs_raw.split("|") if u.strip().startswith("http")]

            # Vision classify existing Shopify images (YES/NO binary)
            shopify_images = [img.get("src", "") for img in product.get("images", []) if img.get("src")]
            all_images = list(dict.fromkeys(shopify_images + extra_images))  # dedupe

            if test_mode:
                print(f"       IMGS: {len(shopify_images)} from Shopify, {len(extra_images)} from scrape, {len(all_images)} total")

            good_images = all_images
            images_deleted = 0
            if all_images:
                classified = classify_images(all_images[:15], api_key)
                good_images = [url for url, cls in classified if cls == "YES"]
                images_deleted = len(classified) - len(good_images)
                if test_mode:
                    for url, cls in classified:
                        print(f"       IMG: {cls} — {url[-50:]}")
                if not good_images:
                    good_images = all_images[:5]
                    images_deleted = 0
                if test_mode:
                    test_stats["images_kept"] += len(good_images)
                    test_stats["images_deleted"] += images_deleted

            # 0-image products: pull from scrape checkpoint
            need_upload = False
            if not good_images:
                if test_mode:
                    print(f"       IMG 0-IMAGE: looking up scrape data...")
                    print(f"       IMG lookup key: '{raw_title[:80]}'")
                    print(f"       IMG scrape_product found: {scrape_product is not None}")
                if scrape_product:
                    imgs_raw = scrape_product.get("product_images", "")
                    main_img = scrape_product.get("product_image", "")
                    all_scraped = []
                    if imgs_raw:
                        all_scraped = [u.strip() for u in imgs_raw.split("|") if u.strip().startswith("http")]
                    if not all_scraped and main_img and main_img.startswith("http"):
                        all_scraped = [main_img]
                    if test_mode:
                        print(f"       IMG scrape lookup: found {len(all_scraped)} image URLs")
                    if all_scraped:
                        classified = classify_images(all_scraped[:10], api_key)
                        good_images = [url for url, cls in classified if cls == "YES"]
                        need_upload = bool(good_images)
                        if test_mode:
                            for url, cls in classified:
                                print(f"       IMG SCRAPE: {cls} — {url[-50:]}")
                            print(f"       IMG SCRAPE: {len(good_images)} YES, need_upload={need_upload}")
                elif test_mode:
                    # Try to diagnose why scrape lookup missed
                    norm_key = normalise(raw_title)
                    print(f"       IMG scrape lookup: MISS")
                    print(f"       IMG norm key: '{norm_key[:80]}'")
                    print(f"       IMG scrape_data has {len(scrape_data)} entries")

            # Generate AI title via vision (using first 1-2 product images)
            ai_title = generate_ai_title(good_images, cached_title, api_key)

            # Re-categorise using the new AI title
            cat_handle, _, parent_handle = categorize(ai_title)
            if test_mode:
                print(f"       CAT: categorize('{ai_title[:60]}') → {cat_handle} (parent: {parent_handle})")
                mapped_id = collection_map.get(cat_handle, "NOT FOUND")
                parent_id = collection_map.get(parent_handle, "NOT FOUND") if parent_handle else "N/A"
                print(f"       CAT MAP: {cat_handle}={mapped_id}, {parent_handle}={parent_id}")

            # Generate description
            desc = generate_description(ai_title, cat_handle, api_key)

            # Save progress BEFORE pushing — crash during push still marks as done
            processed_set.add(pid)
            progress["processed_ids"].append(pid)
            save_progress(progress)

            # Apply fixes
            errs = fix_product(product, ai_title, cat_handle, parent_handle, desc,
                              good_images, token, collection_map,
                              location_id=location_id, test_mode=test_mode)

            # Record the pushed title for future resumability
            save_pushed_title(pid, ai_title, raw_title)

            # Upload images — if product has 0 Shopify images OR we pulled new ones from scrape
            shopify_has_images = len([img for img in product.get("images", []) if img.get("src")])
            should_upload = (need_upload and good_images) or (shopify_has_images == 0 and good_images)
            if test_mode:
                print(f"       IMG DECISION: shopify_has={shopify_has_images}, need_upload={need_upload}, good_images={len(good_images)}, should_upload={should_upload}")
            if should_upload and good_images:
                if test_mode:
                    print(f"       IMG UPLOAD: uploading {len(good_images)} images to product {pid}")
                headers_api = shopify_headers(token)
                base = shopify_base()
                import base64 as b64mod
                img_ok, img_fail = 0, 0
                for img_url in good_images[:9]:
                    try:
                        if test_mode:
                            print(f"       IMG downloading: {img_url[-70:]}")
                        dl = _download_with_retry(img_url)
                        if not dl or dl.status_code != 200 or len(dl.content) < 1000:
                            if test_mode:
                                print(f"       IMG download failed: {dl.status_code} ({len(dl.content)} bytes)")
                            img_fail += 1
                            continue

                        encoded = b64mod.b64encode(dl.content).decode("utf-8")
                        payload = {"image": {"attachment": encoded, "filename": "product.jpg"}}
                        if test_mode:
                            print(f"       IMG POST b64: {len(dl.content)} bytes → product {pid}")
                        ir = requests.post(f"{base}/products/{pid}/images.json",
                            headers=headers_api, json=payload, timeout=60)
                        if test_mode:
                            print(f"       IMG POST response: {ir.status_code} {ir.text[:200]}")

                        if ir.status_code in (200, 201):
                            img_ok += 1
                        else:
                            img_fail += 1
                        time.sleep(0.5)
                    except Exception as e:
                        img_fail += 1
                        errs.append(f"Image upload error: {e}")
                        if test_mode:
                            print(f"       IMG ERROR: {e}")

                # Verify images actually landed
                if test_mode:
                    time.sleep(1)
                    try:
                        vr = requests.get(f"{base}/products/{pid}.json?fields=id,images",
                            headers=headers_api, timeout=15)
                        if vr.status_code == 200:
                            actual = len(vr.json().get("product", {}).get("images", []))
                            print(f"       IMG VERIFY: server has {actual} images (uploaded {img_ok}, failed {img_fail})")
                        else:
                            print(f"       IMG VERIFY: fetch failed {vr.status_code}")
                    except Exception as e:
                        print(f"       IMG VERIFY ERROR: {e}")
                    print(f"       IMG RESULT: {img_ok} uploaded, {img_fail} failed")
            elif not good_images and test_mode:
                print(f"       IMG: product has 0 images — no upload source found")

            # Verify final image count and delete if 0
            final_imgs = -1
            try:
                headers_api = shopify_headers(token)
                base = shopify_base()
                vr = requests.get(f"{base}/products/{pid}.json?fields=id,images",
                    headers=headers_api, timeout=15)
                if vr.status_code == 200:
                    final_imgs = len(vr.json().get("product", {}).get("images", []))
                    if test_mode:
                        print(f"       IMG FINAL: product {pid} has {final_imgs} images on Shopify")
            except Exception:
                pass

            # Delete product if 0 images on server
            if final_imgs == 0:
                if delete_count[0] >= 500:
                    print(f"\n  ⚠ SAFETY HALT: {delete_count[0]} products deleted this run. Stopping to prevent runaway deletion.")
                    print(f"  Review deleted_no_images.json and restart if correct.")
                    save_progress(progress)
                    return
                try:
                    dr = requests.delete(f"{base}/products/{pid}.json", headers=headers_api, timeout=15)
                    if dr.status_code in (200, 204):
                        delete_count[0] += 1
                        # Log deletion
                        del_log = []
                        if DELETED_FILE.exists():
                            del_log = json.loads(DELETED_FILE.read_text())
                        del_log.append({"id": pid, "title": ai_title, "reason": "0 images after processing",
                                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
                        DELETED_FILE.write_text(json.dumps(del_log, indent=2, ensure_ascii=False))
                        print(f"  🗑 DELETED (no images): {pid} — {ai_title[:60]}")
                    else:
                        if test_mode:
                            print(f"       DELETE failed: {dr.status_code} {dr.text[:100]}")
                except Exception as e:
                    if test_mode:
                        print(f"       DELETE error: {e}")

            # Progress already saved before fix_product
            if errs:
                progress["errors"] += 1
                if test_mode:
                    test_stats["api_errors"] += len(errs)
                    print(f"  [{i+1}] ⚠ {ai_title[:50]} — errors: {errs}")
            else:
                progress["matched"] += 1
                if test_mode:
                    print(f"  [{i+1}] ✓ match={match_type} → {cat_handle}")
                    print(f"       NEW TITLE: {ai_title}")
                    print(f"       Admin: https://{config.SHOPIFY_STORE}/admin/products/{pid}")
                    print(f"       imgs: {len(all_images)} total, {len(good_images)} kept, {images_deleted} deleted | variants: {len(product.get('variants', []))}")
                elif (i + 1) % 10 == 0:
                    print(f"  [{i+1}/{len(todo)}] ✓ {ai_title[:50]} → {cat_handle}")

            if not test_mode and (i + 1) % 25 == 0:
                save_progress(progress)
                elapsed = time.time() - t0
                rate = (i + 1) / max(elapsed, 1) * 60
                print(f"  [{i+1}/{len(todo)}] matched={progress['matched']} unmatched={progress['unmatched']} errors={progress['errors']} | {rate:.0f}/min")

        # Save
        save_progress(progress)
        if unmatched:
            UNMATCHED_FILE.write_text(json.dumps(unmatched, indent=2))

        print(f"\n  Summary: matched={progress['matched']} unmatched={progress['unmatched']} errors={progress['errors']}")

        if test_mode:
            matched_total = test_stats["exact"] + test_stats["normalised"] + test_stats.get("subset", 0) + test_stats.get("jaccard", 0) + test_stats.get("image_id", 0)
            total_imgs = test_stats["images_kept"] + test_stats["images_deleted"]
            avg_kept = test_stats["images_kept"] / max(matched_total, 1)
            avg_deleted = test_stats["images_deleted"] / max(matched_total, 1)
            print(f"\n  ══ TEST SUMMARY ══")
            print(f"  Matching:")
            print(f"    Exact match:      {test_stats['exact']}")
            print(f"    Normalised match: {test_stats['normalised']}")
            print(f"    Subset coverage:  {test_stats.get('subset', 0)}")
            print(f"    Jaccard fallback: {test_stats.get('jaccard', 0)}")
            print(f"    Image ID match:   {test_stats['image_id']}")
            print(f"    Unmatched:        {test_stats['unmatched']}")
            print(f"  Images:")
            print(f"    Total classified: {total_imgs}")
            print(f"    Avg kept/product: {avg_kept:.1f}")
            print(f"    Avg deleted/product: {avg_deleted:.1f}")
            print(f"  API errors: {test_stats['api_errors']}")
            print(f"\n  Check these 10 products in Shopify admin:")
            print(f"  - Title reads well?  Description reads well?  Category sensible?")
            print(f"  - Images are all product photos?  First image is nicest?")
            print(f"  - Stock = 10?  Status = Active?")
            print(f"\n  If good: python3 shopify_fixer.py run")
            print(f"  If good + poll: python3 shopify_fixer.py run --poll\n")
            break

        if not poll:
            break

        print(f"  Polling for new products in 10 minutes...")
        time.sleep(600)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    poll = "--poll" in sys.argv
    if mode == "test":
        run(test_mode=True)
    elif mode == "run":
        run(test_mode=False, poll=poll)
    else:
        print("Usage: python3 shopify_fixer.py test|run [--poll]")
