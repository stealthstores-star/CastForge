#!/usr/bin/env python3
"""
Set painting difficulty metafield for all products via Claude Haiku.

1 = Beginner (large flat surfaces — tanks, vehicles, terrain)
2 = Intermediate (figures with detail — infantry, busts, single characters)
3 = Advanced (small intricate — fantasy multi-figure, anime, complex dioramas)

Usage: python3 set_painting_difficulty.py
"""
import json, time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import config
from uploader import get_shopify_token

PROGRESS_FILE = "difficulty_progress.json"


def make_session():
    s = requests.Session()
    retries = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504],
                    allowed_methods=["GET", "POST"], raise_on_status=False)
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s


def classify_difficulty(title, api_key):
    """Use Claude Haiku to classify painting difficulty 1-3."""
    prompt = f"""Classify this resin model's painting difficulty as exactly 1, 2, or 3.

1 = Beginner: large flat surfaces, few details (tanks, vehicles, large terrain, simple buildings)
2 = Intermediate: moderate detail (infantry figures, busts, single character figures, aircraft)
3 = Advanced: small intricate details (fantasy multi-part figures, anime characters, complex dioramas, tiny scale figures)

Product: "{title}"

Reply with ONLY the number 1, 2, or 3."""

    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 5,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30)
        if r.status_code == 200:
            text = r.json()["content"][0]["text"].strip()
            if text in ("1", "2", "3"):
                return int(text)
    except Exception as e:
        print(f"    Haiku error: {e}")
    return 2  # Default intermediate


def load_progress():
    try:
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"done_ids": []}


def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)


def main():
    token = get_shopify_token()
    session = make_session()
    session.headers.update({"Content-Type": "application/json", "X-Shopify-Access-Token": token})
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"
    gql = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}/graphql.json"
    api_key = config.ANTHROPIC_API_KEY

    progress = load_progress()
    done_ids = set(progress["done_ids"])

    print("\n  Setting painting difficulty via Claude Haiku\n")

    url = f"{base}/products.json?limit=250&fields=id,title"
    total_set = 0

    while url:
        r = session.get(url, timeout=30)
        if r.status_code != 200:
            print(f"  API error: {r.status_code}")
            break

        products = r.json().get("products", [])
        for p in products:
            pid = p["id"]
            if pid in done_ids:
                continue

            diff = classify_difficulty(p["title"], api_key)

            # Set metafield via GraphQL
            mutation = """
            mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
              metafieldsSet(metafields: $metafields) {
                metafields { id }
                userErrors { field message }
              }
            }
            """
            variables = {"metafields": [{
                "ownerId": f"gid://shopify/Product/{pid}",
                "namespace": "custom",
                "key": "painting_difficulty",
                "value": str(diff),
                "type": "number_integer"
            }]}
            r2 = session.post(gql, json={"query": mutation, "variables": variables}, timeout=30)
            if r2.status_code == 200:
                data = r2.json().get("data", {}).get("metafieldsSet", {})
                if data.get("userErrors"):
                    print(f"  [{pid}] errors: {data['userErrors']}")
                else:
                    total_set += 1
            else:
                print(f"  [{pid}] error: {r2.status_code}")

            done_ids.add(pid)
            progress["done_ids"] = list(done_ids)
            save_progress(progress)

            if total_set % 50 == 0 and total_set > 0:
                print(f"  ... {total_set} products classified")
            time.sleep(0.3)

        link = r.headers.get("Link", "")
        url = None
        if 'rel="next"' in link:
            for part in link.split(", <"):
                if 'rel="next"' in part:
                    url = part.split(">")[0].lstrip("<")
                    break

    progress["done_ids"] = list(done_ids)
    save_progress(progress)
    print(f"\n  Done! {total_set} products classified.\n")


if __name__ == "__main__":
    main()
