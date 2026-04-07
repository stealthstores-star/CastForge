#!/usr/bin/env python3
"""
Pull AliExpress reviews for ALL products → Shopify metafields.
Uses Playwright with saved login cookies (ali_state.json) to avoid blocks.

Usage:
    python3 pull_reviews.py --dry-run --limit 3   # Test 3 products, no push
    python3 pull_reviews.py --limit 100            # First 100 unprocessed
    python3 pull_reviews.py                        # All products (overnight)
"""
import json, random, re, sys, time, threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests as http
import config
from uploader import get_shopify_token

# ── Files ──
CHECKPOINT_FILE = Path("scrape_checkpoint.json")
PUSHED_TITLES_FILE = Path("pushed_titles.json")
PROGRESS_FILE = Path("reviews_progress.json")
FAILED_FILE = Path("failed_review_pids.json")
ALI_STATE_FILE = Path("ali_state.json")

MAX_REVIEWS = 12

ENGLISH_NAMES = ["Alex", "Sam", "Jordan", "Taylor", "Morgan", "Riley", "Casey", "Jamie",
                 "Robin", "Quinn", "Drew", "Blake", "Avery", "Skyler", "Dakota", "Reese"]

_file_lock = threading.Lock()

# ── Progress ──
def load_progress():
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {"processed_ids": []}

def save_progress(progress):
    with _file_lock:
        PROGRESS_FILE.write_text(json.dumps(progress, indent=2))

def log_failed(ali_id, reason):
    with _file_lock:
        data = []
        if FAILED_FILE.exists():
            data = json.loads(FAILED_FILE.read_text())
        data.append({"ali_id": ali_id, "reason": reason, "time": time.strftime("%Y-%m-%dT%H:%M:%S")})
        FAILED_FILE.write_text(json.dumps(data, indent=2))

# ── Anonymise ──
def anonymise_name(name):
    if not name or name == "Anonymous":
        return random.choice(ENGLISH_NAMES) + "."
    latin_ratio = sum(1 for c in name if ord(c) < 256) / max(len(name), 1)
    if latin_ratio < 0.5:
        return random.choice(ENGLISH_NAMES) + "."
    parts = name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[-1][0]}."
    return name[:8] + "."

# ── Scrape reviews via Playwright ──
JUNK_PATTERNS = {"related items", "sold", "review", "add to cart", "buy now",
                  "free shipping", "aliexpress", "seller", "store", "wishlist"}

def scrape_reviews_playwright(page, ali_product_id, worker_id=0, debug=False):
    """Fetch reviews via searchEvaluation.do API from inside page context (has cookies)."""
    print(f"  [W{worker_id}] fetching {ali_product_id}...", flush=True)

    # First navigate to any AliExpress page to establish cookies in the browser context
    for attempt in range(3):
        try:
            # Navigate to the product page (lightweight, just need the domain cookies active)
            page.goto(f"https://www.aliexpress.com/item/{ali_product_id}.html",
                      wait_until="commit", timeout=20000)
            time.sleep(1)

            # Check for captcha
            if "punish" in page.url.lower() or "x5sec" in page.url.lower():
                print(f"  [W{worker_id}] captcha, waiting 60s...")
                time.sleep(60)
                continue

            # Call the feedback API via fetch() inside the page — carries cookies automatically
            raw = page.evaluate(f"""async () => {{
                try {{
                    const r = await fetch(
                        'https://feedback.aliexpress.com/pc/searchEvaluation.do?productId={ali_product_id}&page=1&pageSize=20&filter=all&sort=complex_default',
                        {{credentials: 'include'}}
                    );
                    return await r.text();
                }} catch(e) {{ return JSON.stringify({{error: e.message}}); }}
            }}""")

            if not raw or len(raw) < 50:
                print(f"  [W{worker_id}] empty response for {ali_product_id}")
                if attempt < 2:
                    time.sleep(5)
                    continue
                return []

            # Parse JSON
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                print(f"  [W{worker_id}] invalid JSON for {ali_product_id}: {raw[:100]}")
                if attempt < 2:
                    time.sleep(5)
                    continue
                return []

            if data.get("error"):
                print(f"  [W{worker_id}] API error: {data['error']}")
                if attempt < 2:
                    time.sleep(5)
                    continue
                return []

            eva_list = (data.get("data") or {}).get("evaViewList") or []

            # Debug: print raw first 2 reviews
            if debug and eva_list:
                print(f"  [W{worker_id}] RAW review structure ({len(eva_list)} total):")
                for j, item in enumerate(eva_list[:2]):
                    print(f"    Review {j+1}: {json.dumps(item, ensure_ascii=False)[:300]}")

            reviews = []
            for item in eva_list:
                name = item.get("buyerName", "")
                # buyerEval is rating in tens (50 = 5 stars, 40 = 4 stars)
                raw_eval = item.get("buyerEval", 50)
                rating = raw_eval // 10 if raw_eval > 5 else raw_eval  # handle both formats
                rating = max(1, min(5, rating))

                text = (item.get("buyerFeedback") or "").strip()

                # Discard junk
                if not text or len(text) < 10:
                    continue
                text_lower = text.lower()
                if any(p in text_lower for p in JUNK_PATTERNS):
                    continue

                date = (item.get("evalDate") or "")[:10]

                images = []
                for img in (item.get("images") or [])[:3]:
                    if isinstance(img, str):
                        u = img if img.startswith("http") else f"https:{img}"
                        images.append(u)
                    elif isinstance(img, dict):
                        u = img.get("url") or img.get("imgUrl") or ""
                        if u:
                            images.append(u if u.startswith("http") else f"https:{u}")

                reviews.append({
                    "name": name,
                    "rating": rating,
                    "text": text[:500],
                    "date": date,
                    "images": images,
                })

            print(f"  [W{worker_id}] got {len(reviews)} reviews for {ali_product_id}")
            return reviews

        except Exception as e:
            err = str(e)[:80]
            if attempt < 2:
                print(f"  [W{worker_id}] attempt {attempt+1} failed for {ali_product_id}: {err}")
                time.sleep(5)
            else:
                print(f"  [W{worker_id}] FAILED {ali_product_id} after 3 attempts: {err}")
                log_failed(ali_product_id, f"error: {err}")
                return []

    return []

def filter_and_sort_reviews(reviews):
    """Filter 4-5★ only, prioritise images, cap at MAX_REVIEWS."""
    filtered = [r for r in reviews if r.get("rating", 5) >= 4]
    filtered.sort(key=lambda r: (-(r.get("rating", 5)), -int(bool(r.get("images")))))
    result = []
    for r in filtered[:MAX_REVIEWS]:
        result.append({
            "name": anonymise_name(r.get("name", "")),
            "rating": r.get("rating", 5),
            "text": r.get("text", "")[:500],
            "date": r.get("date", ""),
            "images": [i for i in r.get("images", []) if i.startswith("http")][:3],
        })
    return result

# ── Batch translate ──
def batch_translate(reviews, api_key):
    needs = [(i, r["text"]) for i, r in enumerate(reviews)
             if r.get("text") and len(r["text"]) > 10
             and sum(1 for c in r["text"] if ord(c) < 128) / max(len(r["text"]), 1) < 0.85]
    if not needs:
        return reviews
    for batch_start in range(0, len(needs), 10):
        batch = needs[batch_start:batch_start + 10]
        texts = [t for _, t in batch]
        try:
            prompt = "Translate these product reviews to natural English. Preserve meaning and tone. Return as a JSON array of strings in the same order.\n\n"
            for j, t in enumerate(texts):
                prompt += f"{j+1}. {t}\n"
            r = http.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-haiku-4-5-20251001", "max_tokens": 2000,
                      "messages": [{"role": "user", "content": prompt}]}, timeout=30)
            if r.status_code == 200:
                m = re.search(r'\[.*\]', r.json()["content"][0]["text"], re.DOTALL)
                if m:
                    translations = json.loads(m.group())
                    for k, (idx, _) in enumerate(batch):
                        if k < len(translations):
                            reviews[idx]["text"] = translations[k]
        except Exception:
            pass
        time.sleep(0.5)
    return reviews

# ── Shopify push ──
def push_reviews_to_shopify(shopify_pid, reviews, token):
    if not reviews:
        return
    total = sum(r["rating"] for r in reviews)
    avg = round(total / len(reviews), 1)
    count = len(reviews)
    dist = {str(i): 0 for i in range(1, 6)}
    for r in reviews:
        dist[str(min(max(r["rating"], 1), 5))] += 1
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"
    for mf in [
        {"namespace": "reviews", "key": "aliexpress", "value": json.dumps(reviews), "type": "json"},
        {"namespace": "reviews", "key": "average", "value": str(avg), "type": "single_line_text_field"},
        {"namespace": "reviews", "key": "count", "value": str(count), "type": "single_line_text_field"},
        {"namespace": "reviews", "key": "distribution", "value": json.dumps(dist), "type": "json"},
    ]:
        for _ in range(3):
            try:
                r = http.post(f"{base}/products/{shopify_pid}/metafields.json",
                    headers=headers, json={"metafield": mf}, timeout=15)
                if r.status_code != 429:
                    break
                time.sleep(float(r.headers.get("Retry-After", 2)))
            except Exception:
                time.sleep(1)
        time.sleep(0.3)

def check_existing_reviews(shopify_pid, token):
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"
    try:
        r = http.get(f"{base}/products/{shopify_pid}/metafields.json?namespace=reviews", headers=headers, timeout=15)
        if r.status_code == 200:
            for mf in r.json().get("metafields", []):
                if mf.get("key") == "count" and int(mf.get("value", "0")) > 0:
                    return True
    except Exception:
        pass
    return False

# ── Main ──
def main():
    dry_run = "--dry-run" in sys.argv
    limit = None
    for i, a in enumerate(sys.argv):
        if a == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])

    api_key = config.ANTHROPIC_API_KEY
    token = get_shopify_token() if not dry_run else None

    if not CHECKPOINT_FILE.exists():
        print("No scrape_checkpoint.json"); return
    if not ALI_STATE_FILE.exists():
        print("No ali_state.json — run the price scraper first to create login cookies"); return

    cp = json.loads(CHECKPOINT_FILE.read_text())
    products = cp.get("products", [])

    pushed = {}
    if PUSHED_TITLES_FILE.exists():
        pushed = json.loads(PUSHED_TITLES_FILE.read_text())

    # Build work list
    shopify_by_ali_id = {}
    for p in products:
        url = p.get("product_url", "")
        m = re.search(r"/item/(\d+)\.html", url)
        if not m:
            continue
        ali_id = m.group(1)
        raw_title = p.get("product_title", "")
        for spid, data in pushed.items():
            if data.get("raw_title") == raw_title:
                shopify_by_ali_id[ali_id] = int(spid)
                break

    progress = load_progress()
    processed_set = set(progress["processed_ids"])

    work = [(ali_id, spid) for ali_id, spid in shopify_by_ali_id.items() if spid not in processed_set]
    if limit:
        work = work[:limit]

    print(f"\n══════════════════════════════════════")
    print(f"  CastForge Review Puller (Playwright)")
    print(f"══════════════════════════════════════")
    print(f"  Products matched: {len(shopify_by_ali_id)}")
    print(f"  Already processed: {len(processed_set)}")
    print(f"  To process: {len(work)}")
    print(f"  Dry run: {dry_run}")
    print(f"  Using ali_state.json for cookies\n")

    if not work:
        print("  Nothing to process.")
        return

    # Use Playwright with saved cookies — sequential scraping (Playwright is not thread-safe)
    # but translation + Shopify push happen in parallel
    from playwright.sync_api import sync_playwright

    stats = {"scraped": 0, "with_reviews": 0, "pushed": 0, "skipped": 0, "timeout": 0}
    t0 = time.time()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, channel="msedge",
            args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="en-GB",
            storage_state=str(ALI_STATE_FILE))
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        # Block images to speed up page loads
        ctx.route("**/*.{png,jpg,jpeg,gif,svg,webp,avif,ico,woff,woff2,ttf,mp4,webm}",
                  lambda route: route.abort())
        page = ctx.new_page()

        for idx, (ali_id, shopify_pid) in enumerate(work):
            # Skip if has existing reviews
            if not dry_run and token and check_existing_reviews(shopify_pid, token):
                stats["skipped"] += 1
                progress["processed_ids"].append(shopify_pid)
                save_progress(progress)
                continue

            # Scrape
            raw_reviews = scrape_reviews_playwright(page, ali_id, worker_id=0, debug=(idx < 3))
            stats["scraped"] += 1

            if raw_reviews:
                reviews = filter_and_sort_reviews(raw_reviews)
                if reviews:
                    stats["with_reviews"] += 1
                    reviews = batch_translate(reviews, api_key)

                    if dry_run:
                        print(f"  [{idx+1}/{len(work)}] ali:{ali_id} → {len(reviews)} reviews (dry run)")
                        for r in reviews[:2]:
                            print(f"    {r['rating']}★ {r['name']}: {r['text'][:80]}")
                    else:
                        push_reviews_to_shopify(shopify_pid, reviews, token)
                        stats["pushed"] += 1

            progress["processed_ids"].append(shopify_pid)
            save_progress(progress)

            if (idx + 1) % 50 == 0 or idx < 3:
                elapsed = time.time() - t0
                rate = (idx + 1) / max(elapsed, 1) * 60
                print(f"  [{idx+1}/{len(work)}] scraped={stats['scraped']} reviews={stats['with_reviews']} "
                      f"pushed={stats['pushed']} skip={stats['skipped']} timeout={stats['timeout']} | {rate:.0f}/min")

            time.sleep(random.uniform(1.0, 2.0))

        page.close()
        ctx.close()
        browser.close()

    elapsed = time.time() - t0
    print(f"\n  Done in {elapsed/60:.0f} min")
    print(f"  Scraped: {stats['scraped']}, With reviews: {stats['with_reviews']}")
    print(f"  Pushed: {stats['pushed']}, Skipped: {stats['skipped']}, Timeouts: {stats['timeout']}\n")

if __name__ == "__main__":
    main()
