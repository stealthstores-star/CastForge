"""
CastForge Shopify CSV Exporter
Generates a Shopify-compatible CSV for bulk import via Admin → Products → Import.
Follows Shopify's exact CSV format including multi-image rows.
"""

import csv
import re


# Shopify CSV columns (official import format)
SHOPIFY_COLUMNS = [
    "Handle", "Title", "Body (HTML)", "Vendor", "Product Category", "Type",
    "Tags", "Published", "Option1 Name", "Option1 Value",
    "Variant SKU", "Variant Grams", "Variant Inventory Tracker",
    "Variant Inventory Qty", "Variant Inventory Policy", "Variant Fulfillment Service",
    "Variant Price", "Variant Compare At Price", "Variant Requires Shipping",
    "Variant Taxable", "Variant Weight Unit",
    "Image Src", "Image Position", "Image Alt Text",
    "SEO Title", "SEO Description", "Status",
]


def _make_handle(title):
    """Generate a URL-safe handle from a product title."""
    handle = title.lower().strip()
    handle = re.sub(r"[^a-z0-9\s-]", "", handle)
    handle = re.sub(r"\s+", "-", handle)
    handle = re.sub(r"-{2,}", "-", handle)
    handle = handle.strip("-")
    return handle[:80]


def export_shopify_csv(products, output_path):
    """
    Export products to Shopify-compatible CSV.

    Each product dict should have:
        title, body_html, product_type, tags, price, compare_at_price,
        image_url, images (pipe-separated), category_handle,
        seo_title, seo_description, sku

    First row per product has all data + main image.
    Subsequent rows with same Handle have additional images only.
    """
    rows = []
    sku_counter = 1

    for product in products:
        handle = _make_handle(product["title"])
        sku = product.get("sku", f"CF-{sku_counter:06d}")
        sku_counter += 1

        # Collect all images
        all_images = []
        main_img = product.get("image_url", "")
        if main_img:
            all_images.append(main_img)

        extra_images_raw = product.get("images", "")
        if extra_images_raw:
            for img in extra_images_raw.split("|"):
                img = img.strip()
                if img and img not in all_images:
                    all_images.append(img)

        tags = product.get("tags", "new")
        if isinstance(tags, list):
            tags = ", ".join(tags)

        # First row — full product data + first image
        first_row = {
            "Handle": handle,
            "Title": product["title"],
            "Body (HTML)": product.get("body_html", ""),
            "Vendor": "CastForge",
            "Product Category": "",
            "Type": product.get("product_type", ""),
            "Tags": tags,
            "Published": "FALSE",  # Draft
            "Option1 Name": "Title",
            "Option1 Value": "Default Title",
            "Variant SKU": sku,
            "Variant Grams": "500",
            "Variant Inventory Tracker": "",
            "Variant Inventory Qty": "",
            "Variant Inventory Policy": "continue",
            "Variant Fulfillment Service": "manual",
            "Variant Price": f"{product.get('price', 0):.2f}",
            "Variant Compare At Price": f"{product.get('compare_at_price', 0):.2f}",
            "Variant Requires Shipping": "TRUE",
            "Variant Taxable": "TRUE",
            "Variant Weight Unit": "kg",
            "Image Src": all_images[0] if all_images else "",
            "Image Position": "1" if all_images else "",
            "Image Alt Text": product["title"][:100] if all_images else "",
            "SEO Title": product.get("seo_title", ""),
            "SEO Description": product.get("seo_description", ""),
            "Status": "draft",
        }
        rows.append(first_row)

        # Additional image rows (same Handle, everything else blank)
        for i, img_url in enumerate(all_images[1:], start=2):
            img_row = {col: "" for col in SHOPIFY_COLUMNS}
            img_row["Handle"] = handle
            img_row["Image Src"] = img_url
            img_row["Image Position"] = str(i)
            img_row["Image Alt Text"] = f"{product['title'][:80]} - Image {i}"
            rows.append(img_row)

    # Write CSV
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SHOPIFY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    product_count = len(products)
    image_count = len(rows)
    print(f"  Exported {product_count} products ({image_count} rows including images) → {output_path}")
    return output_path
