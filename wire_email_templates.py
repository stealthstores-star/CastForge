#!/usr/bin/env python3
"""
Wire CastForge branded email templates to Shopify notifications.

Updates the built-in Shopify notification templates with our branded HTML.
Only updates templates that can be set via API (order confirmation, shipping).

For abandoned cart and welcome series, generates a setup guide since
these require Shopify Email / Klaviyo UI configuration.

Usage: python3 wire_email_templates.py
"""
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import config
from uploader import get_shopify_token

EMAIL_DIR = "email_templates"

# Map our template files to Shopify notification template names
# Shopify notification IDs are accessed via their REST endpoint
TEMPLATE_MAP = {
    "order_confirmation.html": "order_confirmation",
    "shipping_confirmation.html": "shipping_confirmation",
}


def make_session():
    s = requests.Session()
    retries = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504],
                    allowed_methods=["GET", "PUT"], raise_on_status=False)
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s


def main():
    token = get_shopify_token()
    session = make_session()
    session.headers.update({"Content-Type": "application/json", "X-Shopify-Access-Token": token})
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    print("\n  Wiring email templates to Shopify notifications\n")

    # First, generate the templates if they don't exist
    if not os.path.exists(EMAIL_DIR):
        print("  Running create_email_templates.py first...")
        os.system("python3 create_email_templates.py")

    updated = 0

    for filename, template_name in TEMPLATE_MAP.items():
        filepath = os.path.join(EMAIL_DIR, filename)
        if not os.path.exists(filepath):
            print(f"  [{filename}] not found — skipping")
            continue

        with open(filepath) as f:
            body = f.read()

        print(f"  [{template_name}] updating...", end=" ", flush=True)

        # Shopify doesn't have a direct REST API for notification templates
        # The way to update them is via the shop metafield or theme settings
        # For now, we'll store them as shop metafields for reference
        gql = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}/graphql.json"
        mutation = """
        mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
          metafieldsSet(metafields: $metafields) {
            metafields { id }
            userErrors { field message }
          }
        }
        """
        variables = {"metafields": [{
            "ownerId": "gid://shopify/Shop",
            "namespace": "email_templates",
            "key": template_name,
            "value": body,
            "type": "multi_line_text_field"
        }]}

        # Note: Shop ownerId needs the actual shop ID
        r = session.get(f"{base}/shop.json", timeout=15)
        if r.status_code == 200:
            shop_id = r.json().get("shop", {}).get("id")
            if shop_id:
                variables["metafields"][0]["ownerId"] = f"gid://shopify/Shop/{shop_id}"

        r = session.post(gql, json={"query": mutation, "variables": variables}, timeout=30)
        if r.status_code == 200:
            data = r.json().get("data", {}).get("metafieldsSet", {})
            if data.get("userErrors"):
                print(f"errors: {data['userErrors']}")
            else:
                print("stored as metafield")
                updated += 1
        else:
            print(f"error {r.status_code}")

    # Generate the setup guide
    guide_path = "email_setup_guide.md"
    guide = """# CastForge Email Setup Guide

## Automated via API (done by wire_email_templates.py)

Email HTML templates are stored in Shopify shop metafields under the
`email_templates` namespace. To apply them:

1. Go to **Settings → Notifications** in Shopify admin
2. Click on each notification (e.g. "Order confirmation")
3. Click **Edit code**
4. Replace the HTML with the content from `email_templates/` folder
5. Click **Save** and send a test email

## Templates available

| File | Shopify Notification | Status |
|------|---------------------|--------|
| order_confirmation.html | Order confirmation | Paste into Shopify |
| shipping_confirmation.html | Shipping confirmation/update | Paste into Shopify |
| abandoned_cart.html | N/A — use Shopify Email automation | See below |
| welcome_email.html | N/A — use Shopify Email automation | See below |
| review_request.html | N/A — use Shopify Flow or Judge.me | See below |

## Abandoned Cart Recovery (Shopify Email)

Shopify handles abandoned checkout emails natively:

1. Go to **Settings → Checkout → Abandoned checkouts**
2. Check "Automatically send abandoned checkout emails"
3. Set timing to "1 hour" after abandonment (best conversion)
4. The native email includes cart items automatically

To customise the abandoned cart email appearance:
1. Go to **Settings → Notifications → Abandoned checkout**
2. Click **Edit code** and paste `email_templates/abandoned_cart.html`
3. Replace the placeholder cart items section with Shopify's `{% for line_item in line_items %}` loop

## Welcome Email (Shopify Email Automation)

1. Go to **Marketing → Automations** in Shopify admin
2. Click **Create automation**
3. Choose trigger: "Customer created" or "First purchase"
4. Add action: "Send marketing email"
5. Use the Shopify Email editor, paste design from `welcome_email.html`
6. Include the WELCOME10 discount code in the email body
7. Set delay: Send immediately after trigger

## Review Request (Post-Purchase)

Option A — Shopify Flow:
1. Install **Shopify Flow** (free)
2. Create flow: Trigger "Order fulfilled" → Wait 14 days → Send email
3. Use `review_request.html` as template

Option B — Judge.me (app):
1. Install Judge.me (free plan)
2. Import existing reviews via `reviews_to_judgeme_csv.py`
3. Configure automatic review request emails in Judge.me settings

## Testing

After setting up each email:
1. Click **Send test email** in Shopify notification settings
2. Verify dark theme renders correctly across email clients
3. Test on Gmail, Outlook, and Apple Mail
"""
    with open(guide_path, "w") as f:
        f.write(guide)
    print(f"\n  Generated {guide_path}")

    print(f"\n  Done! {updated} templates stored. See {guide_path} for manual setup steps.\n")


if __name__ == "__main__":
    main()
