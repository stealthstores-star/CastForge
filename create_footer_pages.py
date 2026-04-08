#!/usr/bin/env python3
"""
Create all footer pages with pre-written content.
Usage: python3 create_footer_pages.py
"""
import json, sys, time
import requests, config
from uploader import get_shopify_token

PAGES = {
    "faq": {
        "title": "Frequently Asked Questions",
        "body_html": """
<h2>Shipping</h2>
<h3>How long does shipping take?</h3>
<p>Standard delivery is 5-7 business days to the US, EU, and UK. Rest of world typically 10-14 business days. All orders include free tracked shipping.</p>
<h3>Do you ship internationally?</h3>
<p>Yes — we ship worldwide from warehouses in the US, EU, and UK. Free shipping on every order regardless of destination.</p>
<h3>How do I track my order?</h3>
<p>You'll receive a tracking number by email within 48 hours of placing your order. Use it to track your package on our carrier's website.</p>
<h3>Will I have to pay customs or import duties?</h3>
<p>Orders shipping within the US, EU, and UK are typically duty-free. International orders may be subject to local customs charges — these are the responsibility of the buyer.</p>

<h2>Products</h2>
<h3>Are your models painted?</h3>
<p>No — all our resin kits arrive unpainted and unassembled. This gives you complete creative freedom to paint and finish the model however you like.</p>
<h3>What material are the models made from?</h3>
<p>High-quality resin. Resin captures finer detail than plastic injection moulding, making it the preferred material for collectors and competition painters.</p>
<h3>What scale should I choose?</h3>
<p>It depends on your use case. 1/35 is ideal for detailed dioramas, 1/72 for wargaming armies, 28mm for tabletop gaming, and 75mm+ for display painting. See our <a href="/pages/scale-guide">Scale Guide</a> for detailed comparisons.</p>
<h3>Is assembly required?</h3>
<p>Yes — most kits arrive as multi-part assemblies. We recommend cyanoacrylate (super glue) for resin. Clean parts with warm soapy water before priming.</p>
<h3>Do you sell paints and tools?</h3>
<p>We stock select hobby accessories. For paints, we recommend Vallejo, Citadel, or AK Interactive ranges available at your local hobby store.</p>

<h2>Orders & Returns</h2>
<h3>What is your return policy?</h3>
<p>30-day hassle-free returns. Items must be in original packaging and unused. See our <a href="/pages/returns">Returns Policy</a> for full details.</p>
<h3>What if my order arrives damaged?</h3>
<p>Email us a photo within 48 hours of delivery. We'll send a free replacement or full refund — no need to return the damaged item.</p>
<h3>Can I cancel my order?</h3>
<p>Orders can be cancelled within 2 hours of placing. After that, they enter our fulfilment process. Contact us immediately if you need to cancel.</p>
<h3>Do you offer wholesale or bulk pricing?</h3>
<p>Yes — contact us at support@castforge.store for wholesale enquiries on orders of 20+ units.</p>
"""
    },
    "shipping": {
        "title": "Shipping Information",
        "body_html": """
<h2>Delivery Times</h2>
<table><tbody>
<tr><td><strong>United States</strong></td><td>5-7 business days</td></tr>
<tr><td><strong>Europe (EU)</strong></td><td>5-7 business days</td></tr>
<tr><td><strong>United Kingdom</strong></td><td>5-7 business days</td></tr>
<tr><td><strong>Rest of World</strong></td><td>10-14 business days</td></tr>
</tbody></table>

<h2>Free Shipping</h2>
<p>Every order ships free worldwide. No minimum order value. No exceptions.</p>

<h2>Tracking</h2>
<p>All orders are tracked. You'll receive a tracking number by email within 48 hours of placing your order. Tracking updates may take 24-48 hours to appear after dispatch.</p>

<h2>Warehouses</h2>
<p>We ship from warehouses in the United States, European Union, and United Kingdom. Your order is automatically routed to the nearest warehouse for fastest delivery.</p>

<h2>Customs & Duties</h2>
<p>Orders within the US, EU, and UK are typically duty-free as they ship domestically. International orders to other regions may incur local customs charges — these vary by country and are the responsibility of the buyer.</p>

<h2>Packaging</h2>
<p>Every kit is individually wrapped in foam and bubble wrap, then packed in a sturdy outer box. We double-check packaging before dispatch. Resin is fragile — we take extra care.</p>
"""
    },
    "returns": {
        "title": "Returns & Refunds",
        "body_html": """
<h2>30-Day Return Policy</h2>
<p>Not satisfied? Return any item within 30 days of delivery for a full refund. No questions asked.</p>

<h2>Conditions</h2>
<ul>
<li>Items must be in original, unopened packaging</li>
<li>Assembled or painted items cannot be returned</li>
<li>Return shipping is the responsibility of the buyer (unless item arrived damaged or incorrect)</li>
</ul>

<h2>Damaged Items</h2>
<p>If your order arrives damaged, email us a photo within 48 hours. We'll send a free replacement or full refund — <strong>no need to return the damaged item</strong>.</p>

<h2>Wrong Item</h2>
<p>Received the wrong product? Email us and we'll ship the correct item immediately at no cost. Keep the wrong item as our apology.</p>

<h2>How to Return</h2>
<ol>
<li>Email support@castforge.store with your order number</li>
<li>We'll send you a return address and instructions</li>
<li>Ship the item back in its original packaging</li>
<li>Refund processed within 5 business days of receiving the return</li>
</ol>

<h2>Refund Method</h2>
<p>Refunds are issued to the original payment method. Please allow 5-10 business days for the refund to appear on your statement.</p>
"""
    },
    "contact": {
        "title": "Contact Us",
        "body_html": """
<h2>Get in Touch</h2>
<p>We're here to help. Reach out with any questions about products, orders, or the hobby.</p>

<p><strong>Email:</strong> support@castforge.store</p>
<p><strong>Response time:</strong> Within 24 hours (usually much faster)</p>

<h2>Before You Contact Us</h2>
<p>Check our <a href="/pages/faq">FAQ page</a> — your question may already be answered there.</p>
<p>For order issues, please include your order number in the email.</p>
<p>For damaged items, please attach a photo of the damage.</p>
"""
    },
    "scale-guide": {
        "title": "Scale Guide — Understanding Miniature Scales",
        "body_html": """
<h2>What Does "Scale" Mean?</h2>
<p>Scale tells you how the model's size relates to the real thing. 1/35 means the model is 35 times smaller than reality. A 6-foot soldier at 1/35 is about 50mm tall.</p>

<h2>Common Scales</h2>
<table><tbody>
<tr><td><strong>1/6</strong></td><td>~300mm (12")</td><td>Display figures, high detail</td></tr>
<tr><td><strong>1/10</strong></td><td>~180mm (7")</td><td>Bust and large figure display</td></tr>
<tr><td><strong>1/16</strong></td><td>~120mm</td><td>Large-scale figures, busts</td></tr>
<tr><td><strong>1/24</strong></td><td>~75mm</td><td>Cars, large figures</td></tr>
<tr><td><strong>1/35</strong></td><td>~50mm</td><td>Military vehicles, dioramas</td></tr>
<tr><td><strong>1/48</strong></td><td>~38mm</td><td>Aircraft, vehicles</td></tr>
<tr><td><strong>1/56 (28mm)</strong></td><td>~28mm</td><td>Tabletop wargaming (Bolt Action)</td></tr>
<tr><td><strong>1/72</strong></td><td>~25mm</td><td>Aircraft, compact wargaming</td></tr>
<tr><td><strong>1/100 (15mm)</strong></td><td>~15mm</td><td>Flames of War, mass battles</td></tr>
<tr><td><strong>1/144</strong></td><td>~12mm</td><td>Aircraft, compact displays</td></tr>
<tr><td><strong>1/350</strong></td><td>Variable</td><td>Ship models</td></tr>
<tr><td><strong>1/700</strong></td><td>Variable</td><td>Ship models, fleet displays</td></tr>
</tbody></table>

<h2>Which Scale Is Right for You?</h2>
<h3>For Wargaming</h3>
<p>28mm (1/56) is the standard for games like Warhammer and Bolt Action. 15mm (1/100) is popular for Flames of War and larger battle games.</p>
<h3>For Display Painting</h3>
<p>75mm and larger scales (1/10, 1/16) give you the most surface area to show off painting skills. Competition painters typically work at 75mm or bust scale.</p>
<h3>For Dioramas</h3>
<p>1/35 is the gold standard for military dioramas. Enough detail to be realistic, small enough to build a full scene.</p>
<h3>For Beginners</h3>
<p>Start with 1/35 or 28mm — large enough to paint easily, small enough to finish quickly. Build confidence before tackling larger or smaller scales.</p>
"""
    },
    "about": {
        "title": "About CastForge",
        "body_html": """
<h2>The World's Specialist Resin Model Store</h2>
<p>CastForge was founded by hobbyists, for hobbyists. We believe every modeller deserves access to the finest resin kits in the world — without the markup, without the hassle, and without the guesswork.</p>

<h2>What We Do</h2>
<p>We source premium resin miniatures, figures, busts, vehicles, and terrain pieces from specialist casters worldwide. Every product in our catalogue has been evaluated for casting quality, detail accuracy, and value. We reject over 60% of what we review.</p>

<h2>Why Resin?</h2>
<p>Resin captures detail that plastic injection moulding simply can't match. The crisp edges, fine textures, and smooth surfaces make resin the material of choice for serious modellers and competition painters.</p>

<h2>Our Promise</h2>
<ul>
<li><strong>Quality curated:</strong> Every model hand-selected for detail and casting quality</li>
<li><strong>Free worldwide shipping:</strong> No hidden costs, no minimum orders</li>
<li><strong>30-day returns:</strong> Not happy? Full refund, no questions asked</li>
<li><strong>Hobby experts:</strong> Our team paints and builds — we understand what matters</li>
</ul>

<p>Questions? Reach out anytime at <a href="/pages/contact">support@castforge.store</a>.</p>
"""
    },
    "reviews": {
        "title": "Customer Reviews",
        "body_html": """
<h2>What Our Customers Say</h2>
<p>We're a new store collecting our first reviews. Be among the first to share your experience!</p>
<p>After receiving your order, you'll get an email inviting you to leave a review. Your feedback helps other hobbyists find the right models.</p>
<p><a href="/collections/all">Browse our collection →</a></p>
"""
    },
}


def main():
    token = get_shopify_token()
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    print(f"\n  Creating {len(PAGES)} footer pages\n")

    for handle, page_data in PAGES.items():
        print(f"  {page_data['title']}...", end=" ", flush=True)
        r = requests.post(f"{base}/pages.json", headers=headers, json={
            "page": {
                "title": page_data["title"],
                "handle": handle,
                "body_html": page_data["body_html"],
                "published": True
            }
        }, timeout=15)

        if r.status_code in (200, 201):
            print(f"✓ created")
        elif r.status_code == 422:
            # Already exists — update instead
            gr = requests.get(f"{base}/pages.json?handle={handle}", headers=headers, timeout=15)
            if gr.status_code == 200:
                pages = gr.json().get("pages", [])
                if pages:
                    pid = pages[0]["id"]
                    requests.put(f"{base}/pages/{pid}.json", headers=headers,
                        json={"page": {"id": pid, "body_html": page_data["body_html"]}}, timeout=15)
                    print(f"✓ updated existing")
                else:
                    print(f"exists but couldn't find")
            else:
                print(f"already exists")
        else:
            print(f"error {r.status_code}: {r.text[:80]}")
        time.sleep(0.5)

    print(f"\n  Done! All footer pages created.\n")

if __name__ == "__main__":
    main()
