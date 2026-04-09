#!/usr/bin/env python3
"""
Incremental product sync for CraftForge AI.

Fetches products updated in the last 24 hours and re-embeds them.
Run via cron or Cloudflare Cron Triggers.

Usage:
  export VOYAGE_API_KEY=... SHOPIFY_TOKEN=... CF_ACCOUNT_ID=... CF_API_TOKEN=...
  python3 sync_products.py
"""
import json, os, re, sys, time
from datetime import datetime, timedelta
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "v614bh-2z.myshopify.com")
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN", "")
VOYAGE_API_KEY = os.environ.get("VOYAGE_API_KEY", "")
CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "")
CF_API_TOKEN = os.environ.get("CF_API_TOKEN", "")
VECTORIZE_INDEX = "castforge-products"
API_VERSION = "2024-10"


def make_session():
    s = requests.Session()
    retries = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s


def strip_html(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html or '')).strip()


def extract_scale(tags):
    for tag in tags.split(", "):
        if tag.strip().startswith("scale:"):
            return tag.strip().replace("scale:", "").replace("-", "/")
    return ""


def extract_theme(tags, title):
    lower = (tags + " " + title).lower()
    for pattern, theme in [
        (r'ww2|wwii|world war|german|soviet', 'wwii'), (r'modern|seal|swat', 'modern'),
        (r'fantasy|dragon|orc|elf|knight', 'fantasy'), (r'sci-?fi|cyber|robot|mech', 'scifi'),
        (r'anime|manga|waifu', 'anime'), (r'car|motorcycle', 'cars'),
        (r'terrain|building|ruin', 'terrain'), (r'roman|napoleon|viking|samurai', 'historical'),
    ]:
        if re.search(pattern, lower):
            return theme
    return ""


def main():
    if not all([VOYAGE_API_KEY, SHOPIFY_TOKEN]):
        print("Error: Missing environment variables"); sys.exit(1)

    session = make_session()
    since = (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z"

    print(f"\n  Syncing products updated since {since}\n")

    url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/products.json?updated_at_min={since}&limit=250&fields=id,title,handle,body_html,tags,variants,images"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}

    products = []
    while url:
        r = session.get(url, headers=headers, timeout=30)
        if r.status_code != 200: break
        products.extend(r.json().get("products", []))
        link = r.headers.get("Link", "")
        url = None
        if 'rel="next"' in link:
            for part in link.split(", <"):
                if 'rel="next"' in part:
                    url = part.split(">")[0].lstrip("<"); break

    print(f"  Found {len(products)} updated products")
    if not products:
        print("  Nothing to sync"); return

    # Embed in batches of 100
    synced = 0
    for i in range(0, len(products), 100):
        batch = products[i:i+100]
        texts = []
        metas = []
        for p in batch:
            title = p.get("title", "")
            desc = strip_html(p.get("body_html", ""))[:500]
            tags = p.get("tags", "")
            scale = extract_scale(tags)
            theme = extract_theme(tags, title)
            texts.append(f"{title}. {desc}. Scale: {scale}. Theme: {theme}")
            variants = p.get("variants", [])
            images = p.get("images", [])
            metas.append({
                "handle": p.get("handle", ""), "title": title,
                "price": float(variants[0]["price"]) if variants else 0,
                "compare_at_price": float(variants[0].get("compare_at_price") or 0) if variants else None,
                "image": images[0]["src"] if images else "",
                "scale": scale, "theme": theme, "difficulty": 2,
                "in_stock": True, "description_snippet": desc[:200],
            })

        r = session.post("https://api.voyageai.com/v1/embeddings",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {VOYAGE_API_KEY}"},
            json={"model": "voyage-3-lite", "input": texts, "input_type": "document"}, timeout=60)
        if r.status_code != 200: continue
        embeddings = [d["embedding"] for d in r.json()["data"]]

        vectors = []
        for p, emb, meta in zip(batch, embeddings, metas):
            vectors.append({"id": str(p["id"]), "values": emb, "metadata": meta})

        if CF_ACCOUNT_ID and CF_API_TOKEN:
            ndjson = "\n".join(json.dumps(v) for v in vectors)
            session.post(
                f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/vectorize/v2/indexes/{VECTORIZE_INDEX}/upsert",
                headers={"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/x-ndjson"},
                data=ndjson, timeout=60)

        synced += len(batch)
        time.sleep(1)

    print(f"  Synced {synced} products\n")


if __name__ == "__main__":
    main()
