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

# ── Fetch all Shopify products ──
def fetch_all_products(token, fields="id,title,status,tags,images,variants"):
    """Paginate through all Shopify products."""
    headers = shopify_headers(token)
    products = []
    url = f"{shopify_base()}/products.json?limit=250&fields={fields}&status=active"
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

    # 3. Asymmetric subset coverage: ≥90% of Shopify tokens exist in cache entry, AND ≥5 shared
    if cache_tokens:
        shop_tokens = _tokenise(shopify_title)
        if shop_tokens:
            best_coverage, best_shared, best_raw = 0.0, 0, None
            best_jaccard, best_jaccard_raw = 0.0, None

            for raw_title, raw_tokens in cache_tokens.items():
                if not raw_tokens:
                    continue
                inter = shop_tokens & raw_tokens
                shared = len(inter)
                coverage = shared / len(shop_tokens)  # what % of Shopify tokens are in cache
                union = shop_tokens | raw_tokens
                jaccard = shared / len(union)

                # Primary: subset coverage
                if coverage >= 0.90 and shared >= 5 and coverage > best_coverage:
                    best_coverage, best_shared, best_raw = coverage, shared, raw_title

                # Fallback: Jaccard for when Shopify has extra tokens
                if jaccard >= 0.80 and shared >= 5 and jaccard > best_jaccard:
                    best_jaccard, best_jaccard_raw = jaccard, raw_title

            if best_raw:
                return best_raw, ai_cache[best_raw], f"subset({best_coverage:.0%},{best_shared})"
            if best_jaccard_raw:
                return best_jaccard_raw, ai_cache[best_jaccard_raw], f"jaccard({best_jaccard:.0%})"

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

# ── Vision classify images using Haiku 4.5 ──
def _resize_for_vision(url):
    """Download image, resize to 512x512 IN MEMORY ONLY, return base64. Original URL untouched."""
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
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
    """Classify images. Resizes to 512x512 in memory for API only."""
    if not image_urls:
        return []

    results = []
    for i in range(0, len(image_urls), 5):
        batch = image_urls[i:i+5]
        content = []
        valid_batch = []

        for j, url in enumerate(batch):
            b64 = _resize_for_vision(url)
            if b64:
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
                content.append({"type": "text", "text": f"Image {len(valid_batch)+1}:"})
                valid_batch.append(url)
            else:
                results.append((url, "other"))

        if not valid_batch:
            continue

        content.append({"type": "text", "text": """Classify this image. ONE word only: product_photo, text_panel, review_photo, size_chart, logo, packaging, other.
Rules: if >40% of image is text/watermark → text_panel, NEVER product_photo. Reply one per line: "1: product_photo" """})

        try:
            r = requests.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-haiku-4-5-20251001", "max_tokens": 200,
                      "messages": [{"role": "user", "content": content}]},
                timeout=30)
            if r.status_code == 200:
                text = r.json()["content"][0]["text"]
                parsed = {}
                for line in text.strip().split("\n"):
                    m = re.match(r"(\d+):\s*(\w+)", line.strip())
                    if m:
                        parsed[int(m.group(1)) - 1] = m.group(2)
                for j, url in enumerate(valid_batch):
                    results.append((url, parsed.get(j, "product_photo")))
            else:
                for url in valid_batch:
                    results.append((url, "product_photo"))
        except Exception:
            for url in valid_batch:
                results.append((url, "product_photo"))
        time.sleep(0.5)

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

    content.append({"type": "text", "text": f"""Look at this product image and write a clean, SEO-friendly product title for an e-commerce store selling resin models, miniatures, and hobby kits. Include: specific subject (e.g. 'Viking Warrior', 'WWII Tiger Tank', 'Cyber Succubus'), scale if visible, material ('Resin'), and type ('Figure', 'Bust', 'Kit', 'Miniature'). 60-80 chars max. No filler words, no '1/10 Cast Resin Model Assembly Kit GK Unpainted Needs To Be Assembled' junk. The original listing title was: {fallback_title[:100]}. Reply with ONLY the title text, nothing else."""})

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
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 300,
                  "messages": [{"role": "user", "content": f"""Write a 120-word product description for {title}. Category: {category}. Include: specific details from the title, target hobbyist, assembly requirements, one concrete use case. Avoid 'elevate your collection', 'perfect for enthusiasts', 'exceptional craftsmanship'. 2 paragraphs, HTML <p> tags only, no code fences."""}]},
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
                good_images, token, collection_map, test_mode=False):
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

    # 3. Set inventory to 10 for all variants via inventory_levels/set.json
    # Get location ID once
    loc_id = None
    try:
        lr = requests.get(f"{base}/locations.json", headers=headers, timeout=15)
        if lr.status_code == 200:
            locations = lr.json().get("locations", [])
            if locations:
                loc_id = locations[0]["id"]
    except Exception as e:
        errors.append(f"Location fetch error: {e}")

    if loc_id:
        for variant in product.get("variants", []):
            iid = variant.get("inventory_item_id")
            if not iid:
                continue
            try:
                # Enable tracking first
                requests.put(f"{base}/inventory_items/{iid}.json", headers=headers,
                           json={"inventory_item": {"id": iid, "tracked": True}},
                           timeout=15)
                time.sleep(0.3)
                # Set available quantity to 10
                inv_payload = {"location_id": loc_id, "inventory_item_id": iid, "available": 10}
                ir = requests.post(f"{base}/inventory_levels/set.json", headers=headers,
                                 json=inv_payload, timeout=15)
                if test_mode:
                    print(f"       INV variant={variant.get('id')} iid={iid}: {ir.status_code} {ir.text[:150]}")
                if ir.status_code not in (200, 201):
                    errors.append(f"Inventory set failed for variant {variant.get('id')}: {ir.status_code} {ir.text[:100]}")
            except Exception as e:
                errors.append(f"Inventory error variant {variant.get('id')}: {e}")
            time.sleep(0.3)

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

    # Build normalised + token cache indices
    cache_normalised = {}
    cache_tokens = {}
    for raw_title in ai_cache:
        cache_normalised[normalise(raw_title)] = raw_title
        cache_tokens[raw_title] = _tokenise(raw_title)

    token = get_token()
    progress = load_progress() if not test_mode else {"processed_ids": [], "matched": 0, "unmatched": 0, "errors": 0}
    processed_set = set(progress["processed_ids"])
    unmatched = []

    while True:
        # Fetch products
        print(f"\n  Fetching active products from Shopify...")
        products = fetch_all_products(token)
        print(f"  Found {len(products)} active products")

        # Filter already processed
        todo = [p for p in products if p["id"] not in processed_set]
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
        for i, product in enumerate(todo):
            pid = product["id"]
            shopify_title = product.get("title", "")

            # Match
            match = match_product(shopify_title, ai_cache, cache_normalised,
                                  cache_tokens=cache_tokens,
                                  shopify_images=product.get("images", []),
                                  scrape_data=scrape_data)
            if not match:
                progress["unmatched"] += 1
                unmatched.append({"id": pid, "title": shopify_title})
                processed_set.add(pid)
                progress["processed_ids"].append(pid)
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

            # Vision classify existing Shopify images
            shopify_images = [img.get("src", "") for img in product.get("images", []) if img.get("src")]
            all_images = list(dict.fromkeys(shopify_images + extra_images))  # dedupe, preserve order

            good_images = all_images
            images_deleted = 0
            if all_images:
                classified = classify_images(all_images[:15], api_key)
                good_images = [url for url, cls in classified if cls == "product_photo"]
                images_deleted = len(classified) - len(good_images)
                if not good_images:
                    good_images = all_images[:5]
                    images_deleted = 0
                if test_mode:
                    test_stats["images_kept"] += len(good_images)
                    test_stats["images_deleted"] += images_deleted

            # Generate AI title via vision (using first 1-2 product images)
            ai_title = generate_ai_title(good_images, cached_title, api_key)

            # Re-categorise using the new AI title
            cat_handle, _, parent_handle = categorize(ai_title)

            # Generate description
            desc = generate_description(ai_title, cat_handle, api_key)

            # Apply fixes
            errs = fix_product(product, ai_title, cat_handle, parent_handle, desc,
                              good_images, token, collection_map, test_mode=test_mode)

            processed_set.add(pid)
            progress["processed_ids"].append(pid)
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
