#!/usr/bin/env python3
"""
Generate branded email notification templates for CastForge.

Outputs HTML email templates that can be pasted into Shopify's
Settings → Notifications section, or used with Klaviyo/Mailchimp.

Usage: python3 create_email_templates.py
"""
import os

OUTPUT_DIR = "email_templates"

TEMPLATES = {
    "welcome_email.html": {
        "subject": "Welcome to CastForge — Here's 10% Off Your First Order",
        "html": """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Welcome to CastForge</title>
</head>
<body style="margin:0;padding:0;background:#0a0a0a;font-family:'Inter',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;">
<tr><td align="center" style="padding:40px 20px;">
<table width="600" cellpadding="0" cellspacing="0" style="background:#141414;border-radius:12px;border:1px solid #222;">
  <!-- Header -->
  <tr><td style="padding:32px 40px 24px;text-align:center;border-bottom:1px solid #222;">
    <h1 style="font-family:'Bebas Neue',Impact,sans-serif;font-size:36px;color:#c9a84c;margin:0;letter-spacing:2px;">CASTFORGE</h1>
    <p style="font-size:12px;color:#888;margin:4px 0 0;letter-spacing:3px;text-transform:uppercase;">Premium Resin Miniatures</p>
  </td></tr>

  <!-- Body -->
  <tr><td style="padding:40px;">
    <h2 style="font-size:24px;color:#e8e8e8;margin:0 0 16px;font-weight:600;">Welcome to the armoury.</h2>
    <p style="font-size:15px;color:#888;line-height:1.7;margin:0 0 20px;">
      You've joined 4,000+ collectors, painters, and wargamers who trust CastForge for premium resin miniatures. Whether you're building armies, painting display pieces, or crafting dioramas — you're in the right place.
    </p>
    <p style="font-size:15px;color:#888;line-height:1.7;margin:0 0 24px;">
      As a welcome gift, here's <strong style="color:#c9a84c;">10% off</strong> your first order:
    </p>

    <!-- Discount code -->
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:20px 0;">
      <div style="display:inline-block;background:#1a1a1a;border:2px dashed #c9a84c;border-radius:8px;padding:16px 40px;">
        <span style="font-family:'Bebas Neue',Impact,sans-serif;font-size:32px;color:#c9a84c;letter-spacing:4px;">WELCOME10</span>
      </div>
    </td></tr>
    </table>

    <!-- CTA -->
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:24px 0;">
      <a href="{{ shop.url }}/collections/all" style="display:inline-block;background:#c9a84c;color:#000;padding:14px 36px;border-radius:6px;font-weight:700;font-size:14px;text-decoration:none;text-transform:uppercase;letter-spacing:1px;">Browse the Collection</a>
    </td></tr>
    </table>

    <!-- Quick links -->
    <p style="font-size:13px;color:#666;line-height:1.7;margin:24px 0 0;">
      <strong style="color:#888;">Quick links:</strong><br>
      <a href="{{ shop.url }}/pages/scale-guide" style="color:#c9a84c;text-decoration:none;">Scale Guide</a> &nbsp;·&nbsp;
      <a href="{{ shop.url }}/pages/faq" style="color:#c9a84c;text-decoration:none;">FAQ</a> &nbsp;·&nbsp;
      <a href="{{ shop.url }}/blogs/news" style="color:#c9a84c;text-decoration:none;">Blog & Guides</a> &nbsp;·&nbsp;
      <a href="{{ shop.url }}/pages/shipping" style="color:#c9a84c;text-decoration:none;">Shipping Info</a>
    </p>
  </td></tr>

  <!-- Footer -->
  <tr><td style="padding:24px 40px;border-top:1px solid #222;text-align:center;">
    <p style="font-size:11px;color:#555;margin:0;line-height:1.6;">
      CastForge — Premium Resin Miniatures<br>
      <a href="{{ shop.url }}" style="color:#c9a84c;text-decoration:none;">castforge.co.uk</a>
    </p>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""
    },

    "abandoned_cart.html": {
        "subject": "You left something on the workbench — your cart is waiting",
        "html": """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Your CastForge Cart</title>
</head>
<body style="margin:0;padding:0;background:#0a0a0a;font-family:'Inter',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;">
<tr><td align="center" style="padding:40px 20px;">
<table width="600" cellpadding="0" cellspacing="0" style="background:#141414;border-radius:12px;border:1px solid #222;">
  <!-- Header -->
  <tr><td style="padding:32px 40px 24px;text-align:center;border-bottom:1px solid #222;">
    <h1 style="font-family:'Bebas Neue',Impact,sans-serif;font-size:36px;color:#c9a84c;margin:0;letter-spacing:2px;">CASTFORGE</h1>
  </td></tr>

  <!-- Body -->
  <tr><td style="padding:40px;">
    <h2 style="font-size:24px;color:#e8e8e8;margin:0 0 16px;font-weight:600;">Still thinking it over?</h2>
    <p style="font-size:15px;color:#888;line-height:1.7;margin:0 0 20px;">
      You left some models in your cart. Resin miniatures are produced in limited runs — once a batch sells out, restocking can take weeks.
    </p>
    <p style="font-size:15px;color:#888;line-height:1.7;margin:0 0 8px;">
      Here's what's waiting for you:
    </p>

    <!-- Cart items placeholder -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0;border:1px solid #222;border-radius:8px;overflow:hidden;">
      <tr style="background:#1a1a1a;">
        <td style="padding:12px 16px;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid #222;">Item</td>
        <td style="padding:12px 16px;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid #222;text-align:right;">Price</td>
      </tr>
      <!-- Shopify will populate via Liquid: {% for line in checkout.line_items %} -->
      <tr>
        <td style="padding:14px 16px;">
          <span style="font-size:14px;color:#e8e8e8;">{{ line.title }}</span><br>
          <span style="font-size:12px;color:#666;">Qty: {{ line.quantity }}</span>
        </td>
        <td style="padding:14px 16px;text-align:right;font-size:14px;color:#c9a84c;font-weight:600;">{{ line.line_price | money }}</td>
      </tr>
      <!-- {% endfor %} -->
    </table>

    <!-- CTA -->
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:24px 0;">
      <a href="{{ abandoned_checkout_url }}" style="display:inline-block;background:#c9a84c;color:#000;padding:14px 36px;border-radius:6px;font-weight:700;font-size:14px;text-decoration:none;text-transform:uppercase;letter-spacing:1px;">Complete Your Order</a>
    </td></tr>
    </table>

    <!-- Trust signals -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:16px;">
    <tr>
      <td style="font-size:12px;color:#666;text-align:center;padding:4px 0;">🔒 Secure checkout &nbsp;·&nbsp; 🚚 Free worldwide shipping &nbsp;·&nbsp; ↩️ 30-day returns</td>
    </tr>
    </table>
  </td></tr>

  <!-- Footer -->
  <tr><td style="padding:24px 40px;border-top:1px solid #222;text-align:center;">
    <p style="font-size:11px;color:#555;margin:0;line-height:1.6;">
      CastForge — Premium Resin Miniatures<br>
      <a href="{{ shop.url }}" style="color:#c9a84c;text-decoration:none;">castforge.co.uk</a><br>
      <a href="{% customer_login_url %}" style="color:#555;text-decoration:none;font-size:10px;">Manage preferences</a>
    </p>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""
    },

    "order_confirmation.html": {
        "subject": "Order confirmed — your models are being prepared",
        "html": """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Order Confirmed</title>
</head>
<body style="margin:0;padding:0;background:#0a0a0a;font-family:'Inter',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;">
<tr><td align="center" style="padding:40px 20px;">
<table width="600" cellpadding="0" cellspacing="0" style="background:#141414;border-radius:12px;border:1px solid #222;">
  <!-- Header -->
  <tr><td style="padding:32px 40px 24px;text-align:center;border-bottom:1px solid #222;">
    <h1 style="font-family:'Bebas Neue',Impact,sans-serif;font-size:36px;color:#c9a84c;margin:0;letter-spacing:2px;">CASTFORGE</h1>
  </td></tr>

  <!-- Body -->
  <tr><td style="padding:40px;">
    <h2 style="font-size:24px;color:#e8e8e8;margin:0 0 16px;font-weight:600;">Order confirmed!</h2>
    <p style="font-size:15px;color:#888;line-height:1.7;margin:0 0 20px;">
      Thanks for your order, {{ customer.first_name | default: "collector" }}. Your models are being carefully packed and will be dispatched within 48 hours.
    </p>

    <!-- Order summary -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0;background:#1a1a1a;border-radius:8px;border:1px solid #222;">
      <tr>
        <td style="padding:16px 20px;border-bottom:1px solid #222;">
          <span style="font-size:12px;color:#666;text-transform:uppercase;">Order</span><br>
          <span style="font-size:14px;color:#e8e8e8;font-weight:600;">{{ order.name }}</span>
        </td>
        <td style="padding:16px 20px;border-bottom:1px solid #222;text-align:right;">
          <span style="font-size:12px;color:#666;text-transform:uppercase;">Total</span><br>
          <span style="font-size:14px;color:#c9a84c;font-weight:600;">{{ order.total_price | money }}</span>
        </td>
      </tr>
      <tr><td colspan="2" style="padding:16px 20px;">
        <span style="font-size:12px;color:#666;text-transform:uppercase;">Shipping to</span><br>
        <span style="font-size:13px;color:#888;">{{ order.shipping_address.city }}, {{ order.shipping_address.country }}</span>
      </td></tr>
    </table>

    <!-- CTA -->
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:24px 0;">
      <a href="{{ order.order_status_url }}" style="display:inline-block;background:#c9a84c;color:#000;padding:14px 36px;border-radius:6px;font-weight:700;font-size:14px;text-decoration:none;text-transform:uppercase;letter-spacing:1px;">Track Your Order</a>
    </td></tr>
    </table>

    <!-- What's next -->
    <h3 style="font-size:16px;color:#e8e8e8;margin:24px 0 12px;">What happens next?</h3>
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td style="padding:8px 0;font-size:14px;color:#888;vertical-align:top;">
          <span style="color:#c9a84c;font-weight:700;margin-right:8px;">1.</span>
          Your order is packed with care (bubble wrap + rigid box)
        </td>
      </tr>
      <tr>
        <td style="padding:8px 0;font-size:14px;color:#888;vertical-align:top;">
          <span style="color:#c9a84c;font-weight:700;margin-right:8px;">2.</span>
          Tracking number emailed within 48 hours
        </td>
      </tr>
      <tr>
        <td style="padding:8px 0;font-size:14px;color:#888;vertical-align:top;">
          <span style="color:#c9a84c;font-weight:700;margin-right:8px;">3.</span>
          Delivery in 7–15 business days (free worldwide shipping)
        </td>
      </tr>
    </table>

    <!-- Painting tip -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:24px;background:#1a1a1a;border-radius:8px;border:1px solid #222;">
    <tr><td style="padding:16px 20px;">
      <p style="font-size:13px;color:#888;margin:0;line-height:1.6;">
        <strong style="color:#c9a84c;">Pro tip:</strong> While you wait, check out our <a href="{{ shop.url }}/blogs/news" style="color:#c9a84c;text-decoration:none;">painting guides</a> to prep your workspace. Resin models give their best results when washed in warm soapy water before priming.
      </p>
    </td></tr>
    </table>
  </td></tr>

  <!-- Footer -->
  <tr><td style="padding:24px 40px;border-top:1px solid #222;text-align:center;">
    <p style="font-size:11px;color:#555;margin:0;line-height:1.6;">
      CastForge — Premium Resin Miniatures<br>
      <a href="{{ shop.url }}" style="color:#c9a84c;text-decoration:none;">castforge.co.uk</a><br>
      Questions? <a href="{{ shop.url }}/pages/contact" style="color:#c9a84c;text-decoration:none;">Contact us</a>
    </p>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""
    },

    "shipping_confirmation.html": {
        "subject": "Your models are on the way! Tracking inside",
        "html": """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shipping Confirmation</title>
</head>
<body style="margin:0;padding:0;background:#0a0a0a;font-family:'Inter',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;">
<tr><td align="center" style="padding:40px 20px;">
<table width="600" cellpadding="0" cellspacing="0" style="background:#141414;border-radius:12px;border:1px solid #222;">
  <!-- Header -->
  <tr><td style="padding:32px 40px 24px;text-align:center;border-bottom:1px solid #222;">
    <h1 style="font-family:'Bebas Neue',Impact,sans-serif;font-size:36px;color:#c9a84c;margin:0;letter-spacing:2px;">CASTFORGE</h1>
  </td></tr>

  <!-- Body -->
  <tr><td style="padding:40px;">
    <h2 style="font-size:24px;color:#e8e8e8;margin:0 0 16px;font-weight:600;">Your order has shipped!</h2>
    <p style="font-size:15px;color:#888;line-height:1.7;margin:0 0 20px;">
      Great news, {{ customer.first_name | default: "collector" }} — your models are on their way. Here are your tracking details:
    </p>

    <!-- Tracking info -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0;background:#1a1a1a;border-radius:8px;border:1px solid #222;">
      <tr>
        <td style="padding:16px 20px;">
          <span style="font-size:12px;color:#666;text-transform:uppercase;">Order</span><br>
          <span style="font-size:14px;color:#e8e8e8;">{{ order.name }}</span>
        </td>
      </tr>
      <tr>
        <td style="padding:0 20px 16px;">
          <span style="font-size:12px;color:#666;text-transform:uppercase;">Tracking</span><br>
          <a href="{{ fulfillment.tracking_url }}" style="font-size:14px;color:#c9a84c;text-decoration:none;font-weight:600;">{{ fulfillment.tracking_number }}</a>
        </td>
      </tr>
    </table>

    <!-- CTA -->
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:24px 0;">
      <a href="{{ fulfillment.tracking_url }}" style="display:inline-block;background:#c9a84c;color:#000;padding:14px 36px;border-radius:6px;font-weight:700;font-size:14px;text-decoration:none;text-transform:uppercase;letter-spacing:1px;">Track Your Package</a>
    </td></tr>
    </table>

    <p style="font-size:13px;color:#666;line-height:1.7;margin:0;">
      Estimated delivery: 7–15 business days. Tracking updates may take 24–48 hours to appear.
    </p>
  </td></tr>

  <!-- Footer -->
  <tr><td style="padding:24px 40px;border-top:1px solid #222;text-align:center;">
    <p style="font-size:11px;color:#555;margin:0;line-height:1.6;">
      CastForge — Premium Resin Miniatures<br>
      <a href="{{ shop.url }}" style="color:#c9a84c;text-decoration:none;">castforge.co.uk</a>
    </p>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""
    },

    "review_request.html": {
        "subject": "How are your new models? Leave a review",
        "html": """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Review Your Order</title>
</head>
<body style="margin:0;padding:0;background:#0a0a0a;font-family:'Inter',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;">
<tr><td align="center" style="padding:40px 20px;">
<table width="600" cellpadding="0" cellspacing="0" style="background:#141414;border-radius:12px;border:1px solid #222;">
  <!-- Header -->
  <tr><td style="padding:32px 40px 24px;text-align:center;border-bottom:1px solid #222;">
    <h1 style="font-family:'Bebas Neue',Impact,sans-serif;font-size:36px;color:#c9a84c;margin:0;letter-spacing:2px;">CASTFORGE</h1>
  </td></tr>

  <!-- Body -->
  <tr><td style="padding:40px;">
    <h2 style="font-size:24px;color:#e8e8e8;margin:0 0 16px;font-weight:600;">How did your models turn out?</h2>
    <p style="font-size:15px;color:#888;line-height:1.7;margin:0 0 20px;">
      Hi {{ customer.first_name | default: "there" }}, your order from CastForge should have arrived by now. We'd love to hear what you think — your feedback helps other hobbyists make confident purchases.
    </p>

    <p style="font-size:15px;color:#888;line-height:1.7;margin:0 0 24px;">
      Share your experience and help the community:
    </p>

    <!-- Star rating visual -->
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:16px 0;">
      <span style="font-size:36px;letter-spacing:8px;color:#c9a84c;">&#9733;&#9733;&#9733;&#9733;&#9733;</span>
    </td></tr>
    </table>

    <!-- CTA -->
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:16px 0;">
      <a href="{{ shop.url }}/pages/reviews" style="display:inline-block;background:#c9a84c;color:#000;padding:14px 36px;border-radius:6px;font-weight:700;font-size:14px;text-decoration:none;text-transform:uppercase;letter-spacing:1px;">Leave a Review</a>
    </td></tr>
    </table>

    <!-- Incentive -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:20px;background:#1a1a1a;border-radius:8px;border:1px solid #222;">
    <tr><td style="padding:16px 20px;text-align:center;">
      <p style="font-size:13px;color:#888;margin:0;">
        <strong style="color:#c9a84c;">Photo reviews</strong> help the most — snap a pic of your painted model and inspire the community!
      </p>
    </td></tr>
    </table>
  </td></tr>

  <!-- Footer -->
  <tr><td style="padding:24px 40px;border-top:1px solid #222;text-align:center;">
    <p style="font-size:11px;color:#555;margin:0;line-height:1.6;">
      CastForge — Premium Resin Miniatures<br>
      <a href="{{ shop.url }}" style="color:#c9a84c;text-decoration:none;">castforge.co.uk</a>
    </p>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""
    },
}


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"\n  Generating email templates → {OUTPUT_DIR}/\n")

    for filename, data in TEMPLATES.items():
        path = os.path.join(OUTPUT_DIR, filename)
        with open(path, "w") as f:
            f.write(data["html"])
        print(f"  ✓ {filename}")
        print(f"    Subject: {data['subject']}")

    # Write a reference sheet
    ref_path = os.path.join(OUTPUT_DIR, "SUBJECTS.txt")
    with open(ref_path, "w") as f:
        f.write("CastForge Email Template Subjects\n")
        f.write("=" * 50 + "\n\n")
        for filename, data in TEMPLATES.items():
            f.write(f"{filename}\n  Subject: {data['subject']}\n\n")

    print(f"\n  Done! {len(TEMPLATES)} templates written to {OUTPUT_DIR}/")
    print(f"  Subject lines saved to {OUTPUT_DIR}/SUBJECTS.txt")
    print(f"\n  To use: paste each template into Shopify Settings → Notifications\n")


if __name__ == "__main__":
    main()
