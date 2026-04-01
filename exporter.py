"""
CastForge Shopify CSV Exporter
Generates a Shopify-compatible CSV for bulk import via Admin → Products → Import.
Handles multi-variant products and multi-image rows.
Uses the SEO module for handles, alt text, tags, titles, and descriptions.
"""

import csv
import json
import re

from seo import url_handle, image_alt_text, seo_title, meta_description, auto_tags


# Shopify CSV columns (official import format)
SHOPIFY_COLUMNS = [
    "Handle", "Title", "Body (HTML)", "Vendor", "Product Category", "Type",
    "Tags", "Published", "Option1 Name", "Option1 Value",
    "Variant SKU", "Variant Grams", "Variant Inventory Tracker",
    "Variant Inventory Qty", "Variant Inventory Policy", "Variant Fulfillment Service",
    "Variant Price", "Variant Compare At Price", "Variant Requires Shipping",
    "Variant Taxable", "Variant Weight Unit",
    "Image Src", "Image Position", "Image Alt Text",
    "Variant Image",
    "SEO Title", "SEO Description", "Status",
]


def _parse_variations(product):
    """Parse the variations JSON from a product dict."""
    raw = product.get("variations", "")
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return []
    return raw


def _parse_price_gbp(raw):
    """Extract numeric price from string."""
    if not raw:
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", str(raw))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def export_shopify_csv(products, output_path):
    """
    Export products to Shopify-compatible CSV.

    Products with variations become multi-variant Shopify products:
    - First row: full product data + first variant
    - Subsequent rows (same Handle): additional variants with Option1 Value, price, SKU, image
    - Then: additional image rows

    Products without variations get a single "Default Title" variant.
    """
    rows = []
    sku_counter = 1

    for product in products:
        cat = product.get("category_handle", "uncategorized")
        title = product["title"]

        # SEO
        handle = url_handle(title)
        seo_t = seo_title(title, cat)
        seo_d = meta_description(title, cat)

        tags = auto_tags(title, cat)
        extra_tags = product.get("tags", "")
        if extra_tags:
            if isinstance(extra_tags, str):
                extra_tags = [t.strip() for t in extra_tags.split(",") if t.strip()]
            elif isinstance(extra_tags, list):
                extra_tags = extra_tags
            for t in extra_tags:
                if t.lower() not in [x.lower() for x in tags]:
                    tags.append(t)
        tags_str = ", ".join(tags)

        base_sku = product.get("sku", f"CF-{sku_counter:06d}")
        sku_counter += 1

        # Collect all product images
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

        # Parse variations
        variations = _parse_variations(product)
        has_variants = len(variations) > 1

        if has_variants:
            # Determine option name
            option_name = variations[0].get("option_name", "Style")

            # First row: full product data + first variant
            first_var = variations[0]
            var_price = product.get("price", 0)
            var_compare = product.get("compare_at_price", 0)

            # If variant has its own price, use the pricing formula result from product
            # (pricing is already calculated in process_products)
            var_sku = f"{base_sku}-A"
            var_image = first_var.get("image", "")

            first_row = _product_row(
                handle=handle, title=title,
                body_html=product.get("body_html", ""),
                product_type=product.get("product_type", ""),
                tags_str=tags_str,
                option_name=option_name,
                option_value=first_var.get("name", "Default"),
                sku=var_sku,
                price=var_price, compare_at=var_compare,
                image_src=all_images[0] if all_images else "",
                image_pos="1",
                image_alt=image_alt_text(title, 1) if all_images else "",
                variant_image=var_image,
                seo_title=seo_t, seo_desc=seo_d,
            )
            rows.append(first_row)

            # Additional variant rows
            for vi, var in enumerate(variations[1:], start=1):
                letter = chr(ord("A") + vi) if vi < 26 else f"V{vi}"
                var_sku_n = f"{base_sku}-{letter}"
                var_row = _variant_row(
                    handle=handle,
                    option_name=option_name,
                    option_value=var.get("name", f"Variant {vi+1}"),
                    sku=var_sku_n,
                    price=var_price, compare_at=var_compare,
                    variant_image=var.get("image", ""),
                )
                rows.append(var_row)

            # Image rows (after all variants)
            for i, img_url in enumerate(all_images[1:], start=2):
                rows.append(_image_row(handle, img_url, str(i), image_alt_text(title, i)))

        else:
            # Single-variant product (Default Title)
            sku = product.get("sku", base_sku)

            first_row = _product_row(
                handle=handle, title=title,
                body_html=product.get("body_html", ""),
                product_type=product.get("product_type", ""),
                tags_str=tags_str,
                option_name="Title",
                option_value="Default Title",
                sku=sku,
                price=product.get("price", 0),
                compare_at=product.get("compare_at_price", 0),
                image_src=all_images[0] if all_images else "",
                image_pos="1",
                image_alt=image_alt_text(title, 1) if all_images else "",
                variant_image="",
                seo_title=seo_t, seo_desc=seo_d,
            )
            rows.append(first_row)

            for i, img_url in enumerate(all_images[1:], start=2):
                rows.append(_image_row(handle, img_url, str(i), image_alt_text(title, i)))

    # Write CSV
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SHOPIFY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    product_count = len(products)
    total_rows = len(rows)
    print(f"  Exported {product_count} products ({total_rows} rows incl. variants + images) → {output_path}")
    return output_path


def _product_row(handle, title, body_html, product_type, tags_str,
                 option_name, option_value, sku, price, compare_at,
                 image_src, image_pos, image_alt, variant_image,
                 seo_title, seo_desc):
    """Build the first row for a product (full data + first variant)."""
    return {
        "Handle": handle,
        "Title": title,
        "Body (HTML)": body_html,
        "Vendor": "CastForge",
        "Product Category": "",
        "Type": product_type,
        "Tags": tags_str,
        "Published": "FALSE",
        "Option1 Name": option_name,
        "Option1 Value": option_value,
        "Variant SKU": sku,
        "Variant Grams": "500",
        "Variant Inventory Tracker": "",
        "Variant Inventory Qty": "",
        "Variant Inventory Policy": "continue",
        "Variant Fulfillment Service": "manual",
        "Variant Price": f"{price:.2f}" if isinstance(price, (int, float)) else str(price),
        "Variant Compare At Price": f"{compare_at:.2f}" if isinstance(compare_at, (int, float)) else str(compare_at),
        "Variant Requires Shipping": "TRUE",
        "Variant Taxable": "TRUE",
        "Variant Weight Unit": "kg",
        "Image Src": image_src,
        "Image Position": image_pos,
        "Image Alt Text": image_alt,
        "Variant Image": variant_image,
        "SEO Title": seo_title,
        "SEO Description": seo_desc,
        "Status": "draft",
    }


def _variant_row(handle, option_name, option_value, sku, price, compare_at, variant_image):
    """Build an additional variant row (same Handle, only variant fields)."""
    row = {col: "" for col in SHOPIFY_COLUMNS}
    row["Handle"] = handle
    row["Option1 Name"] = option_name
    row["Option1 Value"] = option_value
    row["Variant SKU"] = sku
    row["Variant Grams"] = "500"
    row["Variant Inventory Policy"] = "continue"
    row["Variant Fulfillment Service"] = "manual"
    row["Variant Price"] = f"{price:.2f}" if isinstance(price, (int, float)) else str(price)
    row["Variant Compare At Price"] = f"{compare_at:.2f}" if isinstance(compare_at, (int, float)) else str(compare_at)
    row["Variant Requires Shipping"] = "TRUE"
    row["Variant Taxable"] = "TRUE"
    row["Variant Weight Unit"] = "kg"
    row["Variant Image"] = variant_image
    return row


def _image_row(handle, image_src, position, alt_text):
    """Build an additional image row."""
    row = {col: "" for col in SHOPIFY_COLUMNS}
    row["Handle"] = handle
    row["Image Src"] = image_src
    row["Image Position"] = position
    row["Image Alt Text"] = alt_text
    return row
