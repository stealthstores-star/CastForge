#!/usr/bin/env python3
"""
Create store-wide automatic volume discounts via Shopify GraphQL.

  Buy 2+ items → 10% off
  Buy 3+ items → 15% off
  Buy 5+ items → 20% off

These apply automatically at checkout. No coupon needed.

Usage: python3 setup_volume_discounts.py
"""
import json, time
import requests
import config
from uploader import get_shopify_token


DISCOUNTS = [
    {"title": "Buy 2+ Save 10%", "min_qty": 2, "pct": 10.0},
    {"title": "Buy 3+ Save 15%", "min_qty": 3, "pct": 15.0},
    {"title": "Buy 5+ Save 20%", "min_qty": 5, "pct": 20.0},
]


def graphql(token, query, variables=None):
    """Execute a Shopify GraphQL Admin API query."""
    url = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}/graphql.json"
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    body = {"query": query}
    if variables:
        body["variables"] = variables
    r = requests.post(url, headers=headers, json=body, timeout=30)
    if r.status_code != 200:
        print(f"  GraphQL error: {r.status_code} {r.text[:200]}")
        return None
    data = r.json()
    if data.get("errors"):
        print(f"  GraphQL errors: {json.dumps(data['errors'], indent=2)[:500]}")
    return data.get("data")


def create_discount(token, title, min_qty, pct):
    """Create an automatic percentage discount with minimum quantity."""
    query = """
    mutation discountAutomaticBasicCreate($automaticBasicDiscount: DiscountAutomaticBasicInput!) {
      discountAutomaticBasicCreate(automaticBasicDiscount: $automaticBasicDiscount) {
        automaticDiscountNode { id }
        userErrors { field message }
      }
    }
    """
    variables = {
        "automaticBasicDiscount": {
            "title": title,
            "startsAt": "2024-01-01T00:00:00Z",
            "minimumRequirement": {
                "quantity": {
                    "greaterThanOrEqualToQuantity": str(min_qty)
                }
            },
            "customerGets": {
                "value": {
                    "percentage": pct / 100.0
                },
                "items": {
                    "all": True
                }
            }
        }
    }
    return graphql(token, query, variables)


def main():
    token = get_shopify_token()
    print("\n  Setting up volume discounts\n")

    # First, list existing automatic discounts to avoid duplicates
    list_query = """
    {
      automaticDiscountNodes(first: 50) {
        nodes {
          id
          automaticDiscount {
            ... on DiscountAutomaticBasic {
              title
              status
            }
          }
        }
      }
    }
    """
    data = graphql(token, list_query)
    existing = set()
    if data and data.get("automaticDiscountNodes"):
        for node in data["automaticDiscountNodes"]["nodes"]:
            disc = node.get("automaticDiscount", {})
            if disc.get("title"):
                existing.add(disc["title"])
                print(f"  Existing: {disc['title']} ({disc.get('status', 'unknown')})")

    created = 0
    for d in DISCOUNTS:
        if d["title"] in existing:
            print(f"  [{d['title']}] already exists — skipping")
            continue

        print(f"  Creating: {d['title']}...", end=" ", flush=True)
        result = create_discount(token, d["title"], d["min_qty"], d["pct"])
        if result:
            node = result.get("discountAutomaticBasicCreate", {})
            errors = node.get("userErrors", [])
            if errors:
                print(f"ERRORS: {errors}")
            elif node.get("automaticDiscountNode"):
                print(f"done ({node['automaticDiscountNode']['id']})")
                created += 1
            else:
                print("no ID returned")
        else:
            print("FAILED")
        time.sleep(1)

    print(f"\n  Done! {created} new discounts created.\n")
    print("  Volume tiers are displayed on product pages via product-hero.liquid")
    print("  Discounts apply automatically at checkout.\n")


if __name__ == "__main__":
    main()
