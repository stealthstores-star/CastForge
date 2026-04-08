#!/usr/bin/env python3
"""
CastForge Launch Readiness Checklist.

Audits the Shopify store against a comprehensive checklist,
checking what's done and what still needs manual action.

Usage: python3 launch_checklist.py
"""
import requests
import config
from uploader import get_shopify_token

def check(label, passed, detail=""):
    icon = "✓" if passed else "✗"
    line = f"  {icon} {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    return passed

def main():
    token = get_shopify_token()
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    print("\n" + "=" * 60)
    print("  CASTFORGE LAUNCH CHECKLIST")
    print("=" * 60)

    passed = 0
    total = 0

    # ── Products ──
    print("\n  PRODUCTS")
    print("  " + "-" * 40)

    r = requests.get(f"{base}/products/count.json", headers=headers, timeout=15)
    count = r.json().get("count", 0) if r.status_code == 200 else 0
    total += 1; passed += check("Products imported", count > 100, f"{count} products")

    # Check for products with no images
    r = requests.get(f"{base}/products.json?limit=250&fields=id,title,images", headers=headers, timeout=15)
    prods = r.json().get("products", []) if r.status_code == 200 else []
    no_img = [p for p in prods if len(p.get("images", [])) == 0]
    total += 1; passed += check("All products have images", len(no_img) == 0,
                                 f"{len(no_img)} missing" if no_img else "")

    # Check for draft products
    r = requests.get(f"{base}/products/count.json?status=draft", headers=headers, timeout=15)
    drafts = r.json().get("count", 0) if r.status_code == 200 else 0
    total += 1; passed += check("No draft products", drafts == 0, f"{drafts} drafts" if drafts else "")

    # ── Collections ──
    print("\n  COLLECTIONS")
    print("  " + "-" * 40)

    r = requests.get(f"{base}/custom_collections/count.json", headers=headers, timeout=15)
    cc = r.json().get("count", 0) if r.status_code == 200 else 0
    r = requests.get(f"{base}/smart_collections/count.json", headers=headers, timeout=15)
    sc = r.json().get("count", 0) if r.status_code == 200 else 0
    total += 1; passed += check("Collections created", (cc + sc) >= 15, f"{cc + sc} collections")

    # ── Pages ──
    print("\n  PAGES")
    print("  " + "-" * 40)

    r = requests.get(f"{base}/pages.json?limit=250", headers=headers, timeout=15)
    pages = r.json().get("pages", []) if r.status_code == 200 else []
    handles = [p["handle"] for p in pages]

    required_pages = ["faq", "shipping", "returns", "contact", "scale-guide", "about"]
    for page in required_pages:
        total += 1; passed += check(f"Page: {page}", page in handles)

    # ── Blog ──
    print("\n  BLOG")
    print("  " + "-" * 40)

    r = requests.get(f"{base}/blogs.json", headers=headers, timeout=15)
    blogs = r.json().get("blogs", []) if r.status_code == 200 else []
    blog_id = None
    for b in blogs:
        if b.get("handle") == "news":
            blog_id = b["id"]
    if blog_id:
        r = requests.get(f"{base}/blogs/{blog_id}/articles/count.json", headers=headers, timeout=15)
        articles = r.json().get("count", 0) if r.status_code == 200 else 0
    else:
        articles = 0
    total += 1; passed += check("Blog posts created", articles >= 5, f"{articles} articles")

    # ── Theme ──
    print("\n  THEME FILES")
    print("  " + "-" * 40)

    import os
    theme_dir = "castforge-shopify-theme"

    required_files = [
        "layout/theme.liquid",
        "sections/header.liquid",
        "sections/footer.liquid",
        "sections/main-404.liquid",
        "sections/home-hero.liquid",
        "sections/product-hero.liquid",
        "sections/main-collection.liquid",
        "snippets/product-card.liquid",
        "snippets/cookie-consent.liquid",
        "snippets/analytics.liquid",
        "templates/index.json",
        "templates/product.json",
        "templates/collection.json",
        "templates/404.json",
        "config/settings_schema.json",
    ]
    for f in required_files:
        path = os.path.join(theme_dir, f)
        total += 1; passed += check(f"Theme: {f}", os.path.exists(path))

    # ── Manual checks ──
    print("\n  MANUAL CHECKS (do these yourself)")
    print("  " + "-" * 40)
    manual = [
        "Domain connected and SSL active",
        "Payment provider configured (Stripe/PayPal)",
        "Shipping rates configured",
        "Tax settings verified",
        "GA4 Measurement ID entered in theme settings",
        "Meta Pixel ID entered in theme settings",
        "Clarity Project ID entered in theme settings",
        "Test order placed and fulfilled",
        "Email notifications customised with branded templates",
        "Legal pages: Terms of Service, Privacy Policy",
        "Social media links updated in footer",
        "Announcement bar messages updated",
        "Remove password page / go live",
    ]
    for item in manual:
        print(f"  ○ {item}")

    # ── Summary ──
    print(f"\n{'=' * 60}")
    print(f"  AUTOMATED: {passed}/{total} checks passed")
    print(f"  MANUAL: {len(manual)} items to verify")
    pct = (passed / total * 100) if total > 0 else 0
    if pct == 100:
        print("  STATUS: Ready to launch! Complete manual checks above.")
    elif pct >= 80:
        print("  STATUS: Almost there — fix the items marked ✗")
    else:
        print("  STATUS: Several items need attention")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
