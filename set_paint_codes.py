#!/usr/bin/env python3
"""
Set recommended paint codes for all products via Claude Haiku.

Suggests 5-8 Citadel/Vallejo paint codes appropriate for each model.
Stores as JSON array in custom.paint_codes metafield.

Usage: python3 set_paint_codes.py
"""
import json, time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import config
from uploader import get_shopify_token

PROGRESS_FILE = "paint_codes_progress.json"


def make_session():
    s = requests.Session()
    retries = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504],
                    allowed_methods=["GET", "POST"], raise_on_status=False)
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s


def suggest_paints(title, api_key):
    """Use Claude Haiku to suggest 5-8 paint codes."""
    prompt = f"""Suggest 5-8 paint codes (Citadel and/or Vallejo) for painting this resin model kit:

"{title}"

Rules:
- Mix Citadel and Vallejo brands
- Include base coats, shade/wash, and highlight colors
- Be specific: "Citadel Leadbelcher" not just "silver"
- Format: one paint per line, just the name (e.g. "Vallejo 887 Brown Violet")
- No explanations, just the paint names"""

    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 200,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30)
        if r.status_code == 200:
            text = r.json()["content"][0]["text"].strip()
            codes = [line.strip().lstrip("- •·0123456789.)")
                     for line in text.split("\n") if line.strip()]
            codes = [c.strip() for c in codes if len(c) > 3]
            return codes[:8] if codes else None
    except Exception as e:
        print(f"    Haiku error: {e}")
    return None


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

    print("\n  Setting recommended paint codes via Claude Haiku\n")

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

            codes = suggest_paints(p["title"], api_key)
            if not codes:
                done_ids.add(pid)
                continue

            # Set metafield via GraphQL (JSON list)
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
                "key": "paint_codes",
                "value": json.dumps(codes),
                "type": "json"
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

            if total_set % 25 == 0 and total_set > 0:
                print(f"  ... {total_set} products got paint codes")
            time.sleep(0.5)

        link = r.headers.get("Link", "")
        url = None
        if 'rel="next"' in link:
            for part in link.split(", <"):
                if 'rel="next"' in part:
                    url = part.split(">")[0].lstrip("<")
                    break

    progress["done_ids"] = list(done_ids)
    save_progress(progress)
    print(f"\n  Done! {total_set} products got paint codes.\n")


if __name__ == "__main__":
    main()
