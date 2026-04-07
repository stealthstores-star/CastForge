#!/usr/bin/env python3
"""
Pull AliExpress reviews for ALL products → Shopify metafields.

Usage:
    python3 pull_reviews.py --dry-run --limit 10   # Test: scrape+translate, no push
    python3 pull_reviews.py                         # Full run: all products
    python3 pull_reviews.py --limit 100             # First 100 unprocessed
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

MAX_REVIEWS = 12

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0",
]

ENGLISH_NAMES = ["Alex", "Sam", "Jordan", "Taylor", "Morgan", "Riley", "Casey", "Jamie",
                 "Robin", "Quinn", "Drew", "Blake", "Avery", "Skyler", "Dakota", "Reese"]

# ── Thread safety ──
_file_lock = threading.Lock()
_ali_lock = threading.Lock()
_ali_last = [0.0]

def _ali_throttle():
    """Max ~2 req/s to AliExpress, shared across workers."""
    with _ali_lock:
        now = time.time()
        wait = 0.5 - (now - _ali_last[0])
        if wait > 0:
            time.sleep(wait)
        _ali_last[0] = time.time()
    time.sleep(random.uniform(1.0, 3.0))

# ── Progress ──
def load_progress():
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {"processed_ids": []}

def save_progress(progress):
    with _file_lock:
        PROGRESS_FILE.write_text(json.dumps(progress, indent=2))

# ── Anonymise ──
def anonymise_name(name):
    """First name + last initial. Non-Latin → random English name."""
    if not name or name == "Anonymous":
        return random.choice(ENGLISH_NAMES) + "."
    # Check if mostly Latin
    latin_ratio = sum(1 for c in name if ord(c) < 256) / max(len(name), 1)
    if latin_ratio < 0.5:
        return random.choice(ENGLISH_NAMES) + "."
    parts = name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[-1][0]}."
    return name[:8] + "."

# ── Scrape reviews ──
def scrape_reviews(ali_product_id):
    """Fetch reviews from AliExpress feedback API. Returns raw review list."""
    all_reviews = []
    for page in range(1, 6):
        _ali_throttle()
        try:
            url = "https://feedback.aliexpress.com/pc/searchEvaluation.do"
            params = {
                "productId": ali_product_id,
                "page": page,
                "pageSize": 20,
                "filter": "all",
                "sort": "default",
            }
            r = http.get(url, params=params, timeout=15,
                headers={"User-Agent": random.choice(USER_AGENTS),
                         "Referer": f"https://www.aliexpress.com/item/{ali_product_id}.html"})

            if r.status_code == 429:
                time.sleep(60)
                continue
            if r.status_code != 200:
                break

            # Check for captcha
            text = r.text[:500]
            if "captcha" in text.lower() or "punish" in text.lower():
                time.sleep(60)
                continue

            try:
                data = r.json()
            except Exception:
                break

            items = data.get("data", {}).get("evaViewList", [])
            if not items:
                break

            for item in items:
                rating = item.get("buyerEval", 5)
                if rating < 4:
                    continue  # Skip 1-3★

                review_text = (item.get("buyerFeedback") or "").strip()
                review_date = (item.get("evalDate") or "")[:10]
                reviewer = item.get("buyerName", "")

                images = []
                for img in (item.get("images") or [])[:3]:
                    if isinstance(img, str):
                        images.append(img if img.startswith("http") else f"https:{img}")
                    elif isinstance(img, dict):
                        u = img.get("url") or img.get("imgUrl") or ""
                        if u:
                            images.append(u if u.startswith("http") else f"https:{u}")

                all_reviews.append({
                    "name": anonymise_name(reviewer),
                    "rating": rating,
                    "text": review_text[:500],
                    "date": review_date,
                    "images": images,
                    "_has_images": bool(images),
                    "_original_rating": rating,
                })

        except Exception:
            break

    # Prioritise: 5★+images > 5★ text > 4★+images > 4★ text
    all_reviews.sort(key=lambda r: (
        -(r["_original_rating"]),
        -int(r["_has_images"]),
    ))

    # Take top MAX_REVIEWS, clean up internal keys
    result = []
    for r in all_reviews[:MAX_REVIEWS]:
        result.append({
            "name": r["name"],
            "rating": r["rating"],
            "text": r["text"],
            "date": r["date"],
            "images": r["images"],
        })
    return result

# ── Batch translate ──
def batch_translate(reviews, api_key):
    """Translate non-English reviews in batches of 10."""
    needs_translation = []
    for i, r in enumerate(reviews):
        text = r.get("text", "")
        if not text or len(text) < 10:
            continue
        ascii_ratio = sum(1 for c in text if ord(c) < 128) / max(len(text), 1)
        if ascii_ratio < 0.85:
            needs_translation.append((i, text))

    if not needs_translation:
        return reviews

    # Batch translate 10 at a time
    for batch_start in range(0, len(needs_translation), 10):
        batch = needs_translation[batch_start:batch_start + 10]
        texts = [t for _, t in batch]

        try:
            prompt = "Translate these product reviews to natural English. Preserve meaning and tone. Return as a JSON array of strings in the same order, one translation per input review.\n\n"
            for j, t in enumerate(texts):
                prompt += f"{j+1}. {t}\n"

            r = http.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": "claude-haiku-4-5-20251001", "max_tokens": 2000,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=30)

            if r.status_code == 200:
                response_text = r.json()["content"][0]["text"].strip()
                # Extract JSON array
                m = re.search(r'\[.*\]', response_text, re.DOTALL)
                if m:
                    translations = json.loads(m.group())
                    for k, (idx, _) in enumerate(batch):
                        if k < len(translations):
                            reviews[idx]["text"] = translations[k]
        except Exception:
            pass
        time.sleep(0.5)

    return reviews

# ── Shopify metafield push ──
def push_reviews_to_shopify(shopify_pid, reviews, token):
    """Write reviews + stats to Shopify product metafields."""
    if not reviews:
        return False

    total = sum(r["rating"] for r in reviews)
    avg = round(total / len(reviews), 1)
    count = len(reviews)
    dist = {str(i): 0 for i in range(1, 6)}
    for r in reviews:
        dist[str(min(max(r["rating"], 1), 5))] += 1

    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    metafields = [
        {"namespace": "reviews", "key": "aliexpress", "value": json.dumps(reviews), "type": "json"},
        {"namespace": "reviews", "key": "average", "value": str(avg), "type": "single_line_text_field"},
        {"namespace": "reviews", "key": "count", "value": str(count), "type": "single_line_text_field"},
        {"namespace": "reviews", "key": "distribution", "value": json.dumps(dist), "type": "json"},
    ]

    for mf in metafields:
        for attempt in range(3):
            try:
                r = http.post(f"{base}/products/{shopify_pid}/metafields.json",
                    headers=headers, json={"metafield": mf}, timeout=15)
                if r.status_code == 429:
                    time.sleep(float(r.headers.get("Retry-After", 2)))
                    continue
                break
            except Exception:
                time.sleep(1)
        time.sleep(0.3)

    return True

def check_existing_reviews(shopify_pid, token):
    """Check if product already has reviews metafield. Returns True if fresh reviews exist."""
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"
    try:
        r = http.get(f"{base}/products/{shopify_pid}/metafields.json?namespace=reviews",
            headers=headers, timeout=15)
        if r.status_code == 200:
            mfs = r.json().get("metafields", [])
            for mf in mfs:
                if mf.get("key") == "count":
                    count = int(mf.get("value", "0"))
                    if count > 0:
                        # Check age — skip if updated within 30 days
                        updated = mf.get("updated_at", "")
                        if updated:
                            from datetime import datetime, timezone
                            try:
                                updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                                age_days = (datetime.now(timezone.utc) - updated_dt).days
                                return age_days < 30
                            except Exception:
                                pass
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

    # Load checkpoint + pushed titles
    if not CHECKPOINT_FILE.exists():
        print("No scrape_checkpoint.json"); return
    cp = json.loads(CHECKPOINT_FILE.read_text())
    products = cp.get("products", [])

    pushed = {}
    if PUSHED_TITLES_FILE.exists():
        pushed = json.loads(PUSHED_TITLES_FILE.read_text())

    # Build work list: products with AliExpress IDs matched to Shopify
    # Cross-reference pushed_titles.json for Shopify product IDs
    shopify_by_ali_id = {}  # ali_product_id → shopify_product_id
    for spid, data in pushed.items():
        raw_title = data.get("raw_title", "")
        # Find this product in checkpoint to get AliExpress ID
        for p in products:
            if p.get("product_title") == raw_title:
                ali_url = p.get("product_url", "")
                m = re.search(r"/item/(\d+)\.html", ali_url)
                if m:
                    shopify_by_ali_id[m.group(1)] = int(spid)
                break

    # Also try matching by product ID directly
    for p in products:
        pid = p.get("id", "")
        url = p.get("product_url", "")
        m = re.search(r"/item/(\d+)\.html", url)
        ali_id = m.group(1) if m else pid
        if ali_id and ali_id not in shopify_by_ali_id:
            # Try to find Shopify ID from pushed titles
            for spid, data in pushed.items():
                if data.get("raw_title") == p.get("product_title"):
                    shopify_by_ali_id[ali_id] = int(spid)
                    break

    # Load progress
    progress = load_progress()
    processed_set = set(progress["processed_ids"])

    work = []
    for ali_id, shopify_pid in shopify_by_ali_id.items():
        if shopify_pid in processed_set:
            continue
        work.append((ali_id, shopify_pid))

    if limit:
        work = work[:limit]

    print(f"\n══════════════════════════════════════")
    print(f"  CastForge Review Puller")
    print(f"══════════════════════════════════════")
    print(f"  Products matched: {len(shopify_by_ali_id)}")
    print(f"  Already processed: {len(processed_set)}")
    print(f"  To process: {len(work)}")
    print(f"  Dry run: {dry_run}")
    print(f"  Workers: 8\n")

    if not work:
        print("  Nothing to process.")
        return

    stats = {"scraped": 0, "with_reviews": 0, "translated": 0, "pushed": 0, "skipped_existing": 0, "errors": 0}
    stats_lock = threading.Lock()
    t0 = time.time()

    def process_one(item):
        idx, (ali_id, shopify_pid) = item

        # Check if already has fresh reviews
        if not dry_run and token:
            if check_existing_reviews(shopify_pid, token):
                with stats_lock:
                    stats["skipped_existing"] += 1
                with _file_lock:
                    progress["processed_ids"].append(shopify_pid)
                    save_progress(progress)
                return

        # Scrape reviews
        reviews = scrape_reviews(ali_id)
        with stats_lock:
            stats["scraped"] += 1

        if not reviews:
            with _file_lock:
                progress["processed_ids"].append(shopify_pid)
                save_progress(progress)
            return

        with stats_lock:
            stats["with_reviews"] += 1

        # Translate
        reviews = batch_translate(reviews, api_key)
        with stats_lock:
            stats["translated"] += 1

        # Push to Shopify
        if not dry_run and token:
            push_reviews_to_shopify(shopify_pid, reviews, token)
            with stats_lock:
                stats["pushed"] += 1

        with _file_lock:
            progress["processed_ids"].append(shopify_pid)
            save_progress(progress)

        # Log
        if dry_run:
            print(f"  [{idx+1}/{len(work)}] ali:{ali_id} → {len(reviews)} reviews (dry run)")
            if reviews:
                print(f"    Sample: {reviews[0]['rating']}★ {reviews[0]['name']}: {reviews[0]['text'][:80]}")
        elif (idx + 1) % 50 == 0 or idx < 5:
            elapsed = time.time() - t0
            rate = (idx + 1) / max(elapsed, 1) * 60
            print(f"  [{idx+1}/{len(work)}] ali:{ali_id} — {len(reviews)} reviews | "
                  f"scraped={stats['scraped']} pushed={stats['pushed']} skip={stats['skipped_existing']} | {rate:.0f}/min")

    # Run with thread pool
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(process_one, (i, item)) for i, item in enumerate(work)]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                with stats_lock:
                    stats["errors"] += 1
                print(f"  Worker error: {e}")

    elapsed = time.time() - t0
    print(f"\n  Done in {elapsed/60:.0f} min")
    print(f"  Scraped: {stats['scraped']}, With reviews: {stats['with_reviews']}")
    print(f"  Translated: {stats['translated']}, Pushed: {stats['pushed']}")
    print(f"  Skipped (existing): {stats['skipped_existing']}, Errors: {stats['errors']}\n")

if __name__ == "__main__":
    main()
