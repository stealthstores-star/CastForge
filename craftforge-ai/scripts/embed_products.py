#!/usr/bin/env python3
"""
One-time product embedding job for CraftForge AI.

Fetches all products from Shopify, builds embedding text for each,
calls Voyage AI to generate 512-dim vectors (voyage-3-lite default), then upserts to
Cloudflare Vectorize.

Resumable via progress file. ~$3-5 for 14k products, ~10 minutes.

Usage:
  export VOYAGE_API_KEY=...
  export SHOPIFY_TOKEN=...
  export CF_ACCOUNT_ID=...
  export CF_API_TOKEN=...
  python3 embed_products.py
"""
import json, os, re, sys, time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "v614bh-2z.myshopify.com")
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_TOKEN", "")
VOYAGE_API_KEY = os.environ.get("VOYAGE_API_KEY", "")
CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "")
CF_API_TOKEN = os.environ.get("CF_API_TOKEN", "")
VECTORIZE_INDEX = "castforge-products"
PROGRESS_FILE = "embed_progress.json"
BATCH_SIZE = 100  # Voyage max batch
API_VERSION = "2024-10"


def make_session():
    s = requests.Session()
    retries = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504],
                    allowed_methods=["GET", "POST", "PUT"], raise_on_status=False)
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s


def strip_html(html):
    text = re.sub(r'<[^>]+>', ' ', html or '')
    return re.sub(r'\s+', ' ', text).strip()


def extract_scale(tags):
    for tag in tags.split(", "):
        tag = tag.strip()
        if tag.startswith("scale:"):
            return tag.replace("scale:", "").replace("-", "/")
    return ""


def extract_theme(tags, title):
    lower = (tags + " " + title).lower()
    if re.search(r'ww2|wwii|world war|german|soviet|sherman|tiger|panzer', lower):
        return "wwii"
    if re.search(r'modern|contemporary|seal|swat', lower):
        return "modern"
    if re.search(r'fantasy|dragon|orc|elf|dwarf|wizard|knight|barbarian', lower):
        return "fantasy"
    if re.search(r'sci-?fi|cyber|robot|mech|space', lower):
        return "scifi"
    if re.search(r'anime|manga|schoolgirl|waifu', lower):
        return "anime"
    if re.search(r'car|motorcycle|ferrari|porsche', lower):
        return "cars"
    if re.search(r'terrain|building|ruin|tree|base', lower):
        return "terrain"
    if re.search(r'roman|napoleon|viking|samurai|medieval', lower):
        return "historical"
    return ""


def load_progress():
    try:
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"done_ids": [], "total_tokens": 0, "total_embedded": 0}


def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)


def fetch_all_products(session):
    """Fetch all products from Shopify."""
    products = []
    url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/products.json?limit=250&status=active&published_status=published&fields=id,title,handle,body_html,tags,variants,images"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}

    while url:
        r = session.get(url, headers=headers, timeout=30)
        if r.status_code != 200:
            print(f"  Shopify error: {r.status_code}")
            break

        data = r.json()
        products.extend(data.get("products", []))
        print(f"  Fetched {len(products)} products...", end="\r")

        link = r.headers.get("Link", "")
        url = None
        if 'rel="next"' in link:
            for part in link.split(", <"):
                if 'rel="next"' in part:
                    url = part.split(">")[0].lstrip("<")
                    break
        time.sleep(0.5)

    print(f"  Fetched {len(products)} products total")
    return products


def embed_batch(texts, session):
    """Embed a batch of texts via Voyage AI."""
    r = session.post("https://api.voyageai.com/v1/embeddings",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {VOYAGE_API_KEY}"},
        json={"model": "voyage-3-lite", "input": texts, "input_type": "document"},
        timeout=60)

    if r.status_code != 200:
        print(f"  Voyage error: {r.status_code} {r.text[:200]}")
        return None

    data = r.json()
    tokens = data.get("usage", {}).get("total_tokens", 0)
    embeddings = [d["embedding"] for d in data["data"]]
    return embeddings, tokens


def upsert_vectors(vectors, session):
    """Upsert vectors to Cloudflare Vectorize."""
    # Vectorize REST API
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/vectorize/v2/indexes/{VECTORIZE_INDEX}/upsert"
    headers = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/x-ndjson"}

    # NDJSON format
    ndjson = "\n".join(json.dumps(v) for v in vectors)
    r = session.post(url, headers=headers, data=ndjson, timeout=60)
    if r.status_code != 200:
        print(f"  Vectorize error: {r.status_code} {r.text[:200]}")
        return False
    return True


def main():
    if not VOYAGE_API_KEY:
        print("Error: VOYAGE_API_KEY not set")
        sys.exit(1)
    if not SHOPIFY_TOKEN:
        print("Error: SHOPIFY_TOKEN not set")
        sys.exit(1)

    session = make_session()
    progress = load_progress()
    done_ids = set(progress["done_ids"])

    print("\n  CraftForge AI — Product Embedding Job")
    print("  " + "=" * 50)

    # Fetch all products
    print("\n  Fetching products from Shopify...")
    products = fetch_all_products(session)

    # Filter out already-done products
    to_embed = [p for p in products if p["id"] not in done_ids]
    print(f"\n  {len(to_embed)} products to embed ({len(done_ids)} already done)")

    if not to_embed:
        print("  Nothing to do!")
        return

    total_tokens = progress["total_tokens"]
    total_embedded = progress["total_embedded"]

    # Process in batches
    for i in range(0, len(to_embed), BATCH_SIZE):
        batch = to_embed[i:i + BATCH_SIZE]

        # Build embedding texts
        texts = []
        metadata_list = []
        for p in batch:
            title = p.get("title", "")
            desc = strip_html(p.get("body_html", ""))[:500]
            tags = p.get("tags", "")
            scale = extract_scale(tags)
            theme = extract_theme(tags, title)

            emb_text = f"{title}. {desc}. Scale: {scale}. Theme: {theme}"
            texts.append(emb_text)

            variants = p.get("variants", [])
            images = p.get("images", [])
            price = float(variants[0]["price"]) if variants else 0
            compare_at = float(variants[0].get("compare_at_price") or 0) if variants else 0
            image = images[0]["src"] if images else ""

            metadata_list.append({
                "handle": p.get("handle", ""),
                "title": title,
                "price": price,
                "compare_at_price": compare_at if compare_at > 0 else None,
                "image": image,
                "scale": scale,
                "theme": theme,
                "difficulty": 2,  # Default, updated by set_painting_difficulty.py
                "in_stock": True,
                "description_snippet": desc[:200],
            })

        # Call Voyage
        result = embed_batch(texts, session)
        if not result:
            print(f"  Batch {i // BATCH_SIZE + 1} failed — skipping")
            continue

        embeddings, tokens = result
        total_tokens += tokens

        # Build vector objects for Vectorize
        vectors = []
        for j, (p, emb, meta) in enumerate(zip(batch, embeddings, metadata_list)):
            vectors.append({
                "id": str(p["id"]),
                "values": emb,
                "metadata": meta,
            })

        # Upsert to Vectorize
        if CF_ACCOUNT_ID and CF_API_TOKEN:
            if upsert_vectors(vectors, session):
                total_embedded += len(batch)
        else:
            # Save locally for manual upload
            local_path = f"vectors_batch_{i // BATCH_SIZE:04d}.json"
            with open(local_path, "w") as f:
                json.dump(vectors, f)
            total_embedded += len(batch)

        # Update progress
        for p in batch:
            done_ids.add(p["id"])
        progress["done_ids"] = list(done_ids)
        progress["total_tokens"] = total_tokens
        progress["total_embedded"] = total_embedded
        save_progress(progress)

        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(to_embed) + BATCH_SIZE - 1) // BATCH_SIZE
        cost_est = total_tokens * 0.02 / 1_000_000
        print(f"  Batch {batch_num}/{total_batches}: {len(batch)} products, {tokens} tokens, est. ${cost_est:.4f} total")

        time.sleep(1)  # Rate limit

    cost_est = total_tokens * 0.02 / 1_000_000
    print(f"\n  Done!")
    print(f"  Total embedded: {total_embedded}")
    print(f"  Total tokens: {total_tokens:,}")
    print(f"  Estimated cost: ${cost_est:.2f}")
    print()


if __name__ == "__main__":
    main()
