#!/usr/bin/env python3
"""
Pull AliExpress reviews for products and store as Shopify metafields.

Usage:
    python3 pull_reviews.py               # Top 50 products by sales
    python3 pull_reviews.py --all         # All products with source URLs
    python3 pull_reviews.py --product PID # Single Shopify product ID
"""
import json, re, sys, time
from pathlib import Path
import requests
import config
from uploader import get_shopify_token

CHECKPOINT_FILE = Path("scrape_checkpoint.json")
MAX_REVIEWS = 12

def get_aliexpress_reviews(product_id, max_reviews=MAX_REVIEWS):
    """Fetch reviews from AliExpress product page via feedback API."""
    reviews = []
    for page in range(1, 4):
        try:
            url = f"https://feedback.aliexpress.com/pc/searchEvaluation.do"
            params = {
                "productId": product_id,
                "page": page,
                "pageSize": 20,
                "filter": "all",
                "sort": "default",
            }
            r = requests.get(url, params=params, timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"})
            if r.status_code != 200:
                break
            data = r.json()
            for item in data.get("data", {}).get("evaViewList", []):
                name = item.get("buyerName", "Anonymous")
                # Anonymise: first name + last initial
                parts = name.split()
                if len(parts) >= 2:
                    name = f"{parts[0]} {parts[-1][0]}."
                elif name:
                    name = name[:8] + "."

                rating = item.get("buyerEval", 5)
                text = item.get("buyerFeedback", "").strip()
                date = item.get("evalDate", "")
                images = []
                for img in item.get("images", [])[:3]:
                    if isinstance(img, str):
                        images.append(img if img.startswith("http") else f"https:{img}")
                    elif isinstance(img, dict):
                        url = img.get("url", img.get("imgUrl", ""))
                        if url:
                            images.append(url if url.startswith("http") else f"https:{url}")

                if text or images:
                    reviews.append({
                        "name": name,
                        "rating": rating,
                        "text": text[:500],
                        "date": date[:10] if date else "",
                        "images": images
                    })
                if len(reviews) >= max_reviews:
                    break
            if len(reviews) >= max_reviews:
                break
        except Exception as e:
            print(f"    Review fetch error page {page}: {e}")
            break
        time.sleep(1)
    return reviews

def translate_review(text, api_key):
    """Translate non-English review text to English via Haiku."""
    if not text or len(text) < 10:
        return text
    # Quick check: if mostly ASCII, probably English
    ascii_ratio = sum(1 for c in text if ord(c) < 128) / max(len(text), 1)
    if ascii_ratio > 0.85:
        return text
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 200,
                  "messages": [{"role": "user", "content": f"Translate this product review to natural English. Reply with ONLY the translation:\n\n{text}"}]},
            timeout=15)
        if r.status_code == 200:
            return r.json()["content"][0]["text"].strip()
    except Exception:
        pass
    return text

def compute_stats(reviews):
    """Compute average rating and distribution."""
    if not reviews:
        return 0, 0, {}
    total = sum(r["rating"] for r in reviews)
    avg = round(total / len(reviews), 1)
    dist = {str(i): 0 for i in range(1, 6)}
    for r in reviews:
        dist[str(min(max(r["rating"], 1), 5))] += 1
    return avg, len(reviews), dist

def push_to_shopify(shopify_pid, reviews, avg, count, dist, token):
    """Write reviews to Shopify product metafields."""
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    metafields = [
        {"namespace": "reviews", "key": "aliexpress", "value": json.dumps(reviews), "type": "json"},
        {"namespace": "reviews", "key": "average", "value": str(avg), "type": "single_line_text_field"},
        {"namespace": "reviews", "key": "count", "value": str(count), "type": "single_line_text_field"},
        {"namespace": "reviews", "key": "distribution", "value": json.dumps(dist), "type": "json"},
    ]
    for mf in metafields:
        mf["owner_id"] = shopify_pid
        mf["owner_resource"] = "product"
        try:
            r = requests.post(f"{base}/products/{shopify_pid}/metafields.json",
                headers=headers, json={"metafield": mf}, timeout=15)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 2)))
                r = requests.post(f"{base}/products/{shopify_pid}/metafields.json",
                    headers=headers, json={"metafield": mf}, timeout=15)
        except Exception:
            pass
        time.sleep(0.5)

def main():
    api_key = config.ANTHROPIC_API_KEY
    token = get_shopify_token()

    # Load scrape checkpoint for AliExpress product IDs
    if not CHECKPOINT_FILE.exists():
        print("No scrape_checkpoint.json found")
        return
    cp = json.loads(CHECKPOINT_FILE.read_text())
    products = cp.get("products", [])

    # Build aliexpress_id → scrape_product lookup
    ali_lookup = {}
    for p in products:
        pid = p.get("id", "")
        url = p.get("product_url", "")
        if pid:
            ali_lookup[pid] = p
        m = re.search(r"/item/(\d+)\.html", url)
        if m:
            ali_lookup[m.group(1)] = p

    # Get Shopify products to process
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    mode = sys.argv[1] if len(sys.argv) > 1 else "--top50"

    if mode == "--product":
        shopify_pid = sys.argv[2]
        r = requests.get(f"{base}/products/{shopify_pid}.json?fields=id,title,tags",
            headers=headers, timeout=15)
        shopify_products = [r.json()["product"]] if r.status_code == 200 else []
    else:
        # Fetch all products
        shopify_products = []
        url = f"{base}/products.json?limit=250&fields=id,title,tags,metafields"
        while url:
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code != 200:
                break
            shopify_products.extend(r.json().get("products", []))
            url = None
            link = r.headers.get("Link", "")
            if 'rel="next"' in link:
                for part in link.split(","):
                    if 'rel="next"' in part:
                        url = part.split("<")[1].split(">")[0]
            time.sleep(0.5)

        if mode != "--all":
            shopify_products = shopify_products[:50]

    print(f"\nPulling reviews for {len(shopify_products)} products\n")

    done, skipped = 0, 0
    for i, sp in enumerate(shopify_products):
        spid = sp["id"]
        title = sp.get("title", "")

        # Find AliExpress product ID from tags
        ali_pid = None
        for tag in (sp.get("tags", "") or "").split(","):
            tag = tag.strip()
            if tag.startswith("source:"):
                m = re.search(r"/item/(\d+)\.html", tag)
                if m:
                    ali_pid = m.group(1)
                    break

        if not ali_pid:
            skipped += 1
            continue

        print(f"  [{i+1}] {title[:50]} (ali:{ali_pid})...", end=" ", flush=True)

        reviews = get_aliexpress_reviews(ali_pid)
        if not reviews:
            print("0 reviews")
            skipped += 1
            continue

        # Translate non-English reviews
        for rev in reviews:
            rev["text"] = translate_review(rev["text"], api_key)

        avg, count, dist = compute_stats(reviews)
        push_to_shopify(spid, reviews, avg, count, dist, token)
        done += 1
        print(f"{count} reviews (avg {avg}★)")

    print(f"\nDone: {done} products with reviews, {skipped} skipped\n")

if __name__ == "__main__":
    main()
