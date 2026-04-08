#!/usr/bin/env python3
"""
Set meta description for every product.

Format: First 155 chars of description (stripped of HTML) + CTA.
Skips products that already have a meta description.
Resumable via progress file.

Usage: python3 update_meta_descriptions.py
"""
import json, re, time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import config
from uploader import get_shopify_token

PROGRESS_FILE = "meta_desc_progress.json"
CTA = " Free worldwide shipping. Shop now."
MAX_LEN = 155


def make_session():
    """Create a requests.Session with automatic retry on connection errors."""
    s = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=2,            # 2, 4, 8, 16, 32s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def strip_html(html):
    """Strip HTML tags and decode entities."""
    text = re.sub(r'<[^>]+>', ' ', html or '')
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&nbsp;', ' ').replace('&#39;', "'").replace('&quot;', '"')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


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
    session.headers.update({
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": token,
    })
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    progress = load_progress()
    done_ids = set(progress["done_ids"])

    print("\n  Updating product meta descriptions\n")

    url = f"{base}/products.json?limit=250&fields=id,title,body_html,metafields_global_description_tag"
    total_updated = 0
    total_skipped = 0

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

            # Check if already has meta description via metafield
            mf_url = f"{base}/products/{pid}/metafields.json?namespace=global&key=description_tag"
            mf_r = session.get(mf_url, timeout=30)
            if mf_r.status_code == 200:
                mfs = mf_r.json().get("metafields", [])
                if mfs and mfs[0].get("value", "").strip():
                    done_ids.add(pid)
                    total_skipped += 1
                    continue

            # Build meta description from body_html
            body = strip_html(p.get("body_html", ""))
            if not body:
                body = p.get("title", "")

            # Truncate to fit CTA within 160 chars total
            max_body = MAX_LEN - len(CTA)
            if len(body) > max_body:
                body = body[:max_body].rsplit(' ', 1)[0] + '...'
            meta_desc = body + CTA

            # Set via metafield
            r2 = session.post(
                f"{base}/products/{pid}/metafields.json",
                json={"metafield": {
                    "namespace": "global",
                    "key": "description_tag",
                    "value": meta_desc,
                    "type": "single_line_text_field"
                }},
                timeout=30,
            )
            if r2.status_code in (200, 201):
                total_updated += 1
            else:
                print(f"  [{pid}] error: {r2.status_code}")
            time.sleep(0.5)

            done_ids.add(pid)
            progress["done_ids"] = list(done_ids)
            save_progress(progress)

            if total_updated % 50 == 0 and total_updated > 0:
                print(f"  ... {total_updated} products updated")

        # Pagination
        link = r.headers.get("Link", "")
        url = None
        if 'rel="next"' in link:
            for part in link.split(", <"):
                if 'rel="next"' in part:
                    url = part.split(">")[0].lstrip("<")
                    break

    progress["done_ids"] = list(done_ids)
    save_progress(progress)
    print(f"\n  Done! {total_updated} meta descriptions set, {total_skipped} already had one.\n")


if __name__ == "__main__":
    main()
