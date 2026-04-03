"""
CastForge Shopify Uploader
Uploads products via Admin REST API with collection assignment.
Chunked upload with auto-resume support.
"""

import json
import math
import os
import time
import csv
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

import config


def get_shopify_token():
    """Exchange client credentials for a Shopify access token (with retries)."""
    for attempt in range(4):
        try:
            resp = requests.post(
                f"https://{config.SHOPIFY_STORE}/admin/oauth/access_token",
                json={
                    "client_id": config.SHOPIFY_CLIENT_ID,
                    "client_secret": config.SHOPIFY_CLIENT_SECRET,
                    "grant_type": "client_credentials",
                },
                timeout=15,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Token exchange failed: {resp.status_code}")
            return resp.json()["access_token"]
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError):
            wait = 2 ** (attempt + 1)
            if attempt < 3:
                print(f"  Token exchange error, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


class ShopifyUploader:
    def __init__(self):
        self.token = get_shopify_token()
        self.base_url = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"
        self.headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": self.token,
        }
        self.collection_map = self._load_collection_map()
        self.sku_counter = self._get_next_sku()
        self.results = {"success": 0, "failed": 0, "skipped": 0, "product_ids": []}
        self.failed_products = []
        self._lock = threading.Lock()

    def _load_collection_map(self):
        path = os.path.join(os.path.dirname(__file__) or ".", "collection_map.json")
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
        return {}

    def _get_next_sku(self):
        try:
            resp = requests.get(f"{self.base_url}/products/count.json",
                                headers=self.headers, timeout=15)
            if resp.status_code == 200:
                return resp.json().get("count", 0) + 1
        except Exception:
            pass
        return 1

    def _next_sku(self):
        sku = f"CF-{self.sku_counter:06d}"
        self.sku_counter += 1
        return sku

    def _api_call(self, method, url, json_data=None, retries=3):
        """API call with 30s timeout, rate limit handling, retry on 502/timeout."""
        for attempt in range(retries):
            try:
                resp = requests.request(method, url, headers=self.headers,
                                         json=json_data, timeout=30)
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", 2))
                    time.sleep(retry_after)
                    continue
                if resp.status_code == 502 and attempt < retries - 1:
                    time.sleep(3)
                    continue
                return resp
            except (requests.exceptions.Timeout, requests.exceptions.SSLError,
                    requests.exceptions.ConnectionError) as e:
                if attempt < retries - 1:
                    time.sleep(3)
                else:
                    raise
        return resp

    def upload_product(self, product):
        """Upload a single product. Stores source_url as tag for matching."""
        sku = self._next_sku()
        tags = product.get("tags", [])
        if isinstance(tags, list):
            tags = list(tags)
        else:
            tags = [t.strip() for t in str(tags).split(",") if t.strip()]

        # Add source URL as tag for matching back later
        source_url = product.get("source_url", "")
        if source_url:
            tags.append(f"source:{source_url[:200]}")

        tags_str = ", ".join(tags)

        payload = {
            "product": {
                "title": product["title"],
                "body_html": product.get("body_html", ""),
                "vendor": "CastForge",
                "product_type": product.get("product_type", ""),
                "tags": tags_str,
                "status": "draft",
                "variants": [
                    {
                        "price": str(product.get("price", "0.00")),
                        "compare_at_price": str(product.get("compare_at_price", "0.00")),
                        "sku": sku,
                        "inventory_policy": "continue",
                        "requires_shipping": True,
                        "weight": 0.5,
                        "weight_unit": "kg",
                    }
                ],
                "metafields_global_title_tag": product.get("seo_title", ""),
                "metafields_global_description_tag": product.get("seo_description", ""),
            }
        }

        # Images — pass through as-is, exact order from scraper
        all_images = []
        img_url = product.get("image_url")
        if img_url and img_url.startswith("http"):
            all_images.append({"src": img_url})

        images_raw = product.get("images", "")
        if images_raw:
            for extra in images_raw.split("|"):
                extra = extra.strip()
                if extra and extra.startswith("http") and extra != img_url:
                    all_images.append({"src": extra})

        if all_images:
            payload["product"]["images"] = all_images

        try:
            resp = self._api_call("POST", f"{self.base_url}/products.json", payload)
        except Exception as e:
            with self._lock:
                self.results["failed"] += 1
                self.failed_products.append({"title": product["title"][:80],
                                              "error": str(e)[:100]})
            return None

        if resp.status_code == 201:
            product_id = resp.json()["product"]["id"]
            with self._lock:
                self.results["product_ids"].append(product_id)
                self.results["success"] += 1

            self._assign_collections(product_id,
                                      product.get("category_handle"),
                                      product.get("parent_handle"))
            time.sleep(config.RATE_LIMIT_DELAY)
            return product_id
        else:
            err_msg = ""
            try:
                err_msg = json.dumps(resp.json().get("errors", ""))[:100]
            except Exception:
                err_msg = resp.text[:100]
            with self._lock:
                self.results["failed"] += 1
                self.failed_products.append({"title": product["title"][:80],
                                              "error": f"HTTP {resp.status_code}: {err_msg}"})
            return None

    def _assign_collections(self, product_id, category_handle, parent_handle):
        handles = [h for h in [category_handle, parent_handle] if h]
        for handle in handles:
            collection_id = self.collection_map.get(handle)
            if not collection_id:
                continue
            try:
                self._api_call("POST", f"{self.base_url}/collects.json",
                                {"collect": {"product_id": product_id,
                                             "collection_id": collection_id}})
            except Exception:
                pass
            time.sleep(0.2)

    def upload_chunk(self, products, chunk_num, total_chunks):
        """Upload a chunk with 2 concurrent threads to max Shopify rate limit."""
        total = len(products)
        print(f"\n  ── Chunk {chunk_num}/{total_chunks}: {total} products (2 threads) ──\n")

        done = [0]  # mutable counter for progress

        def _upload_one(product):
            pid = self.upload_product(product)
            with self._lock:
                done[0] += 1
                d = done[0]
            if d % 50 == 0 or d == total:
                print(f"    [{d}/{total}] {self.results['success']} OK, "
                      f"{self.results['failed']} failed")
            return pid

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(_upload_one, products))

        return self.results

    def save_failed(self, path="failed_uploads.csv"):
        if self.failed_products:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["title", "error"])
                w.writeheader()
                w.writerows(self.failed_products)
            print(f"  Failed uploads: {len(self.failed_products)} → {path}")

    def print_summary(self):
        r = self.results
        print(f"\n  {'='*50}")
        print(f"  Upload Summary")
        print(f"  {'='*50}")
        print(f"  Uploaded:  {r['success']}")
        print(f"  Failed:    {r['failed']}")
        print(f"  Skipped:   {r['skipped']}")
        print(f"  Total IDs: {len(r['product_ids'])}")
        print(f"  {'='*50}")


def nuke_all_products():
    """Delete ALL products from Shopify store."""
    token = get_shopify_token()
    headers = {"X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    all_ids = []
    for status in ["draft", "active", "archived"]:
        url = f"{base}/products.json?status={status}&limit=250&fields=id"
        while url:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 2)))
                continue
            all_ids.extend(p["id"] for p in r.json().get("products", []))
            link = r.headers.get("Link", "")
            url = None
            if 'rel="next"' in link:
                for part in link.split(","):
                    if 'rel="next"' in part:
                        url = part.split("<")[1].split(">")[0]

    print(f"  Found {len(all_ids)} products to delete")

    deleted = 0
    for i, pid in enumerate(all_ids):
        while True:
            r = requests.delete(f"{base}/products/{pid}.json",
                                headers=headers, timeout=30)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 2)))
                continue
            break
        if r.status_code == 200:
            deleted += 1
        if (i + 1) % 50 == 0 or (i + 1) == len(all_ids):
            print(f"    [{i+1}/{len(all_ids)}] Deleted {deleted}")
        time.sleep(0.3)

    print(f"  Done: {deleted} products deleted")
    return deleted
