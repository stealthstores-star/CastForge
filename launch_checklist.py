#!/usr/bin/env python3
"""
CastForge Launch Readiness Checklist.

Audits the Shopify store against a comprehensive checklist,
checking what's done and what still needs manual action.

Can run in offline mode (theme files only) if Shopify credentials
are unavailable.

Usage: python3 launch_checklist.py
"""
import os
import requests
import config

THEME_DIR = "castforge-shopify-theme"


def check(label, passed, detail=""):
    icon = "✓" if passed else "✗"
    line = f"  {icon} {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    return int(passed)


def get_token():
    """Try to get Shopify token, return None if unavailable."""
    try:
        from uploader import get_shopify_token
        return get_shopify_token()
    except Exception:
        return None


def check_shopify(token):
    """Run Shopify API checks. Returns (passed, total)."""
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"
    passed = 0
    total = 0

    # ── Products ──
    print("\n  PRODUCTS")
    print("  " + "-" * 40)

    r = requests.get(f"{base}/products/count.json", headers=headers, timeout=15)
    count = r.json().get("count", 0) if r.status_code == 200 else 0
    total += 1; passed += check("Products imported", count > 100, f"{count} products")

    r = requests.get(f"{base}/products.json?limit=250&fields=id,title,images", headers=headers, timeout=15)
    prods = r.json().get("products", []) if r.status_code == 200 else []
    no_img = [p for p in prods if len(p.get("images", [])) == 0]
    total += 1; passed += check("All products have images", len(no_img) == 0,
                                 f"{len(no_img)} missing" if no_img else "")

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

    return passed, total


def check_theme():
    """Run theme file checks. Returns (passed, total)."""
    passed = 0
    total = 0

    print("\n  THEME FILES")
    print("  " + "-" * 40)

    required_files = [
        "layout/theme.liquid",
        "sections/header.liquid",
        "sections/footer.liquid",
        "sections/main-404.liquid",
        "sections/home-hero.liquid",
        "sections/product-hero.liquid",
        "sections/main-collection.liquid",
        "sections/product-related.liquid",
        "sections/product-recently-viewed.liquid",
        "sections/search-overlay.liquid",
        "sections/header-group.json",
        "sections/footer-group.json",
        "snippets/product-card.liquid",
        "snippets/cart-drawer.liquid",
        "snippets/quick-view-modal.liquid",
        "snippets/cookie-consent.liquid",
        "snippets/analytics.liquid",
        "snippets/social-proof-ticker.liquid",
        "snippets/exit-intent.liquid",
        "snippets/trust-bar.liquid",
        "snippets/checkout-badges.liquid",
        "snippets/scale-filter-bar.liquid",
        "snippets/localization-selector.liquid",
        "snippets/size-comparison.liquid",
        "snippets/ab-test.liquid",
        "snippets/help-button.liquid",
        "snippets/featured-in-strip.liquid",
        "sections/bundle-builder.liquid",
        "sections/product-urgency.liquid",
        "sections/product-tabs.liquid",
        "templates/index.json",
        "templates/product.json",
        "templates/collection.json",
        "templates/404.json",
        "config/settings_schema.json",
        "assets/homepage.css",
        "assets/header.css",
        "assets/product-hero.css",
    ]
    for f in required_files:
        path = os.path.join(THEME_DIR, f)
        total += 1; passed += check(f"{f}", os.path.exists(path))

    return passed, total


def check_scripts():
    """Check that required scripts exist."""
    passed = 0
    total = 0

    print("\n  SCRIPTS")
    print("  " + "-" * 40)

    required_scripts = [
        "setup_volume_discounts.py",
        "update_alt_text.py",
        "update_meta_descriptions.py",
        "generate_brand_assets.py",
        "create_scale_guide.py",
        "create_blog_posts.py",
        "create_collection_seo.py",
        "create_email_templates.py",
        "create_footer_pages.py",
        "round_prices.py",
        "set_painting_difficulty.py",
        "set_paint_codes.py",
        "generate_community_gallery.py",
        "create_category_landing_templates.py",
        "wire_email_templates.py",
    ]
    for s in required_scripts:
        total += 1; passed += check(s, os.path.exists(s))

    return passed, total


def main():
    print("\n" + "=" * 60)
    print("  CASTFORGE LAUNCH CHECKLIST")
    print("=" * 60)

    total_passed = 0
    total_checks = 0

    # Try Shopify API checks
    token = get_token()
    if token:
        p, t = check_shopify(token)
        total_passed += p
        total_checks += t
    else:
        print("\n  SHOPIFY API")
        print("  " + "-" * 40)
        print("  ○ Skipped — no Shopify credentials available")
        print("    Run with valid SHOPIFY_CLIENT_ID/SECRET to check products, collections, pages")

    # Theme file checks (always work)
    p, t = check_theme()
    total_passed += p
    total_checks += t

    # Script checks
    p, t = check_scripts()
    total_passed += p
    total_checks += t

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
        "Run: python3 setup_volume_discounts.py",
        "Run: python3 update_alt_text.py",
        "Run: python3 update_meta_descriptions.py",
        "Run: python3 generate_brand_assets.py",
        "Run: python3 create_scale_guide.py",
        "Run: python3 create_blog_posts.py",
        "Run: python3 create_collection_seo.py",
    ]
    for item in manual:
        print(f"  ○ {item}")

    # ── Summary ──
    print(f"\n{'=' * 60}")
    print(f"  AUTOMATED: {total_passed}/{total_checks} checks passed")
    print(f"  MANUAL: {len(manual)} items to verify")
    pct = (total_passed / total_checks * 100) if total_checks > 0 else 0
    if pct == 100:
        print("  STATUS: All automated checks passed! Complete manual items above.")
    elif pct >= 80:
        print("  STATUS: Almost there — fix the items marked ✗")
    else:
        print("  STATUS: Several items need attention")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
