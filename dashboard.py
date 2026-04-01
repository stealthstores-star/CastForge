"""
CastForge Pipeline Dashboard — Streamlit Web UI

Run with:  streamlit run dashboard.py
"""

import io
import csv
import json
import math
import os
import re
import time

import streamlit as st

import config
import compliance
import categorizer
from exporter import export_shopify_csv

# ── Page config ──────────────────────────────────────────────
st.set_page_config(
    page_title="CastForge Pipeline",
    page_icon="🔥",
    layout="wide",
)

st.title("🔥 CastForge Product Pipeline")
st.markdown("Upload an AliExpress CSV → Compliance scan → Categorize → Price → Export or Upload")

# ── Sidebar settings ─────────────────────────────────────────
with st.sidebar:
    st.header("Settings")
    gbp_to_usd = st.number_input("GBP → USD rate", value=config.GBP_TO_USD, step=0.01)
    compare_at_mult = st.number_input("Compare-at multiplier", value=config.COMPARE_AT_MULTIPLIER, step=0.05)
    min_price = st.number_input("Min price (USD)", value=config.MIN_PRICE_USD, step=0.50)
    compliance_mode = st.selectbox("Compliance mode", ["strict", "moderate"], index=0)

    st.markdown("---")
    st.markdown("**Shopify credentials** (from env vars)")
    has_shopify = bool(os.environ.get("SHOPIFY_CLIENT_ID"))
    st.markdown(f"Client ID: {'✅ Set' if has_shopify else '❌ Not set'}")


# ── Pricing functions ────────────────────────────────────────
def parse_price(raw):
    if not raw:
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", str(raw))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def round_to_99(price):
    return math.floor(price) + 0.99


def calc_price(price_gbp, shipping_gbp):
    total_cost = price_gbp + shipping_gbp
    price_a = (total_cost + 7.50) / 0.95
    price_b = total_cost / 0.60
    selling_gbp = max(price_a, price_b)
    selling_usd = round_to_99(selling_gbp * gbp_to_usd)
    selling_usd = max(selling_usd, min_price)
    compare_usd = round_to_99(selling_usd * compare_at_mult)
    return round(selling_usd, 2), round(compare_usd, 2)


# ── Column detection ─────────────────────────────────────────
COLUMN_ALIASES = {
    "title": ["product_title", "title", "name", "product_name"],
    "price": ["product_price", "price", "cost", "ali_price"],
    "image_url": ["product_image", "image_url", "main_image", "image"],
    "images": ["product_images", "images", "additional_images"],
    "shipping": ["shipping", "shipping_cost", "ship_cost"],
}


def detect_col(headers, field):
    for alias in COLUMN_ALIASES.get(field, [field]):
        for h in headers:
            if h.lower().strip() == alias.lower():
                return h
    return None


# ── Main UI ──────────────────────────────────────────────────
uploaded_file = st.file_uploader("📁 Drop your AliExpress CSV here", type=["csv"])

if uploaded_file is not None:
    # Parse CSV
    raw_text = uploaded_file.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(raw_text))
    headers = reader.fieldnames

    col_title = detect_col(headers, "title")
    col_price = detect_col(headers, "price")
    col_image = detect_col(headers, "image_url")
    col_images = detect_col(headers, "images")
    col_shipping = detect_col(headers, "shipping")

    if not col_title:
        st.error(f"No title column found. Headers: {headers}")
        st.stop()

    products = []
    for row in reader:
        products.append({
            "title": row.get(col_title, "").strip(),
            "raw_price": row.get(col_price, "0") if col_price else "0",
            "image_url": row.get(col_image, "") if col_image else "",
            "images": row.get(col_images, "") if col_images else "",
            "raw_shipping": row.get(col_shipping, "0") if col_shipping else "0",
        })

    st.success(f"Loaded **{len(products)}** products")

    # ── Run pipeline ──────────────────────────────────────
    if st.button("🚀 Run Full Pipeline", type="primary"):
        progress = st.progress(0, text="Starting compliance scan...")

        # Step 1: Compliance
        blocked, warnings, clean, changed = compliance.compliance_report(products)
        progress.progress(30, text=f"Compliance done. {len(blocked)} blocked, {len(changed)} cleaned.")

        if blocked:
            st.session_state["blocked"] = blocked

        # Step 2: Categorize + Price
        uploadable = clean + changed
        progress.progress(40, text=f"Categorizing {len(uploadable)} products...")

        upload_ready = []
        category_counts = {}
        for i, p in enumerate(uploadable):
            title = categorizer.clean_title(p["title"])
            handle, score, parent = categorizer.categorize(title)
            category_counts[handle] = category_counts.get(handle, 0) + 1
            scale = categorizer.detect_scale(p.get("title", title))

            price_gbp = parse_price(p.get("raw_price", "0"))
            shipping_gbp = parse_price(p.get("raw_shipping", "0"))
            sell_usd, compare_usd = calc_price(price_gbp, shipping_gbp)

            body_html = categorizer.generate_description(title, handle, scale)
            parent_name = categorizer.PARENT_DISPLAY_NAMES.get(parent, "Collectible") if parent else "Collectible"

            # Use full-size first image if available
            image_url = p.get("image_url", "")
            images_raw = p.get("images", "")
            if images_raw:
                first_full = images_raw.split("|")[0].strip()
                if first_full:
                    image_url = first_full

            upload_ready.append({
                "title": title,
                "body_html": body_html,
                "product_type": parent_name,
                "tags": "new",
                "price": sell_usd,
                "compare_at_price": compare_usd,
                "image_url": image_url,
                "images": images_raw,
                "category_handle": handle,
                "parent_handle": parent,
                "seo_title": categorizer.generate_seo_title(title),
                "seo_description": categorizer.generate_seo_description(title),
            })

            pct = 40 + int(50 * (i + 1) / len(uploadable))
            progress.progress(pct, text=f"Processing {i+1}/{len(uploadable)}...")

        progress.progress(95, text="Generating export...")

        # Export Shopify CSV
        export_path = "shopify_import.csv"
        export_shopify_csv(upload_ready, export_path)
        progress.progress(100, text="Pipeline complete!")

        # ── Results ───────────────────────────────────
        st.markdown("---")
        st.header("📊 Results")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total", len(products))
        col2.metric("Blocked", len(blocked))
        col3.metric("Ready", len(upload_ready))
        col4.metric("Warnings", len(warnings))

        # Category breakdown
        st.subheader("Category Breakdown")
        cat_data = []
        for handle in sorted(category_counts, key=category_counts.get, reverse=True):
            name = categorizer.CATEGORY_DISPLAY_NAMES.get(handle, handle)
            cat_data.append({"Category": name, "Count": category_counts[handle]})
        st.table(cat_data)

        # Price samples
        st.subheader("Price Samples (first 10)")
        price_data = []
        for p in upload_ready[:10]:
            price_data.append({
                "Title": p["title"][:60],
                "Price": f"${p['price']:.2f}",
                "Compare At": f"${p['compare_at_price']:.2f}",
                "Category": p["category_handle"],
            })
        st.table(price_data)

        # Download button
        with open(export_path, "r") as f:
            csv_data = f.read()
        st.download_button(
            "📥 Download Shopify Import CSV",
            csv_data,
            file_name="shopify_import.csv",
            mime="text/csv",
        )

        # Compliance report
        if os.path.exists("castforge_compliance_report.txt"):
            with open("castforge_compliance_report.txt") as f:
                report = f.read()
            with st.expander("📋 Full Compliance Report"):
                st.text(report)

    # ── Blocked products review ───────────────────────
    if "blocked" in st.session_state and st.session_state["blocked"]:
        st.markdown("---")
        st.subheader(f"🚫 Blocked Products ({len(st.session_state['blocked'])})")
        if st.button("Review Blocked Products"):
            for bp in st.session_state["blocked"]:
                with st.expander(f"❌ {bp.get('original_title', bp.get('title', '?'))[:80]}"):
                    st.markdown(f"**Title:** {bp.get('original_title', bp.get('title', ''))}")
                    st.markdown(f"**Reason:** {'; '.join(bp.get('issues', []))}")
                    img = bp.get("image_url", "")
                    if img:
                        st.image(img, width=200)
