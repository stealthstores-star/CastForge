#!/usr/bin/env python3
"""
Round all product prices to .99 pricing and set compare-at prices.
Price → round up to nearest .99
Compare-at → price × 1.30, rounded to .99

Usage:
    python3 round_prices.py --dry-run    # Preview changes
    python3 round_prices.py              # Apply changes
"""
import json, math, sys, time
import requests, config
from uploader import get_shopify_token

def round_to_99(cents):
    """Round up to nearest X.99 in cents. E.g. 1732 → 1799, 999 → 999."""
    dollars = cents / 100.0
    rounded = math.ceil(dollars) - 0.01  # e.g. 17.32 → 18 → 17.99
    if rounded < 4.99:
        rounded = 4.99
    return int(round(rounded * 100))

def main():
    dry_run = "--dry-run" in sys.argv
    token = get_shopify_token()
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    print(f"\n  {'DRY RUN — ' if dry_run else ''}Rounding prices to .99 + setting compare-at\n")

    # Fetch all products
    products = []
    for status in ["active", "draft"]:
        url = f"{base}/products.json?limit=250&fields=id,title,variants&status={status}"
        while url:
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 2))); continue
            if r.status_code != 200: break
            products.extend(r.json().get("products", []))
            url = None
            link = r.headers.get("Link", "")
            for part in link.split(", <"):
                if 'rel="next"' in part: url = part.split(">")[0].lstrip("<"); break
            time.sleep(0.5)
    print(f"  {len(products)} products fetched\n")

    updated = 0
    for i, p in enumerate(products):
        changed = False
        variant_updates = []
        for v in p.get("variants", []):
            price_cents = int(round(float(v.get("price", "0")) * 100))
            new_price_cents = round_to_99(price_cents)
            new_compare_cents = round_to_99(int(new_price_cents * 1.30))

            if new_price_cents != price_cents or not v.get("compare_at_price"):
                changed = True
                variant_updates.append({
                    "id": v["id"],
                    "price": f"{new_price_cents / 100:.2f}",
                    "compare_at_price": f"{new_compare_cents / 100:.2f}"
                })

        if changed and variant_updates:
            if dry_run:
                old = p["variants"][0].get("price", "?")
                new = variant_updates[0]["price"]
                comp = variant_updates[0]["compare_at_price"]
                if updated < 10:
                    print(f"    {p['title'][:50]}: ${old} → ${new} (was ${comp})")
            else:
                try:
                    r = requests.put(f"{base}/products/{p['id']}.json", headers=headers,
                        json={"product": {"id": p["id"], "variants": variant_updates}}, timeout=15)
                    if r.status_code == 429:
                        time.sleep(float(r.headers.get("Retry-After", 2)))
                        r = requests.put(f"{base}/products/{p['id']}.json", headers=headers,
                            json={"product": {"id": p["id"], "variants": variant_updates}}, timeout=15)
                except Exception:
                    pass
                time.sleep(0.3)
            updated += 1

        if (i+1) % 500 == 0:
            print(f"    ...{i+1}/{len(products)} checked, {updated} updated", flush=True)

    print(f"\n  Done: {updated} products {'would be' if dry_run else ''} updated\n")

if __name__ == "__main__":
    main()
