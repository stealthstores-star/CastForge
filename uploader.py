"""
CastForge Shopify Uploader
Uploads products via Admin REST API with collection assignment.
"""

import json
import math
import os
import time

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
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Token exchange failed: {resp.status_code} {resp.text[:200]}")
            return resp.json()["access_token"]
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError):
            wait = 2 ** (attempt + 1)
            if attempt < 3:
                print(f"  Token exchange connection error, retrying in {wait}s...")
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

    def _load_collection_map(self):
        path = os.path.join(os.path.dirname(__file__) or ".", "collection_map.json")
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
        print("  Warning: collection_map.json not found — skipping collection assignment")
        return {}

    def _get_next_sku(self):
        """Determine next SKU number from existing products."""
        resp = requests.get(
            f"{self.base_url}/products/count.json",
            headers=self.headers,
        )
        if resp.status_code == 200:
            return resp.json().get("count", 0) + 1
        return 1

    def _next_sku(self):
        sku = f"CF-{self.sku_counter:06d}"
        self.sku_counter += 1
        return sku

    def _api_call(self, method, url, json_data=None, retries=4):
        """Make API call with rate limit handling, SSL retry, and backoff."""
        for attempt in range(retries):
            try:
                resp = requests.request(method, url, headers=self.headers, json=json_data)
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", 2))
                    print(f"    Rate limited, waiting {retry_after}s...")
                    time.sleep(retry_after)
                    continue
                return resp
            except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
                wait = 2 ** (attempt + 1)
                if attempt < retries - 1:
                    print(f"    Connection error, retrying in {wait}s... ({attempt+1}/{retries})")
                    time.sleep(wait)
                else:
                    raise
        return resp

    def upload_product(self, product):
        """
        Upload a single product to Shopify.
        Product dict keys: title, body_html, product_type, tags, price,
        compare_at_price, image_url, category_handle, parent_handle, seo_title,
        seo_description.
        """
        sku = self._next_sku()
        tags = product.get("tags", [])
        if isinstance(tags, list):
            tags = ", ".join(tags)

        payload = {
            "product": {
                "title": product["title"],
                "body_html": product.get("body_html", ""),
                "vendor": "CastForge",
                "product_type": product.get("product_type", ""),
                "tags": tags,
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

        # Add image
        img_url = product.get("image_url")
        if img_url:
            payload["product"]["images"] = [{"src": img_url}]

        resp = self._api_call("POST", f"{self.base_url}/products.json", payload)

        if resp.status_code == 201:
            product_id = resp.json()["product"]["id"]
            self.results["product_ids"].append(product_id)
            self.results["success"] += 1

            # Assign to collections
            self._assign_collections(
                product_id,
                product.get("category_handle"),
                product.get("parent_handle"),
            )

            time.sleep(config.RATE_LIMIT_DELAY)
            return product_id
        else:
            self.results["failed"] += 1
            print(f"    FAIL [{resp.status_code}]: {product['title'][:50]}")
            if resp.status_code != 429:
                try:
                    err = resp.json()
                    print(f"           {json.dumps(err.get('errors', err))[:150]}")
                except Exception:
                    pass
            return None

    def _assign_collections(self, product_id, category_handle, parent_handle):
        """Assign product to its subcategory and parent collections."""
        handles = [h for h in [category_handle, parent_handle] if h]
        for handle in handles:
            collection_id = self.collection_map.get(handle)
            if not collection_id:
                continue
            resp = self._api_call(
                "POST",
                f"{self.base_url}/collects.json",
                {"collect": {"product_id": product_id, "collection_id": collection_id}},
            )
            if resp.status_code not in (201, 200):
                pass  # Non-critical — product still uploaded
            time.sleep(0.2)

    def upload_batch(self, products):
        """Upload a list of products with progress reporting."""
        total = len(products)
        print(f"\n  Uploading {total} products to Shopify (as drafts)...\n")

        for i, product in enumerate(products):
            pid = self.upload_product(product)
            status = "OK" if pid else "FAIL"
            if (i + 1) % 10 == 0 or (i + 1) == total:
                print(f"  [{i+1}/{total}] {status} — {product['title'][:55]}")

        return self.results

    def print_summary(self):
        """Print upload summary."""
        r = self.results
        print(f"\n  {'='*50}")
        print(f"  Upload Summary")
        print(f"  {'='*50}")
        print(f"  Uploaded:  {r['success']}")
        print(f"  Failed:    {r['failed']}")
        print(f"  Skipped:   {r['skipped']}")
        print(f"  Total IDs: {len(r['product_ids'])}")
        print(f"  {'='*50}")
