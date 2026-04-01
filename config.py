"""CastForge Pipeline Configuration."""

import os

# ── Shopify ───────────────────────────────────────────────────
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "v614bh-2z.myshopify.com")
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
API_VERSION = "2024-10"

# ── Anthropic (Claude Vision for image scanning) ──────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "sk-ant-xxx")

# ── Compliance Settings ───────────────────────────────────────
COMPLIANCE_MODE = "strict"       # "strict" blocks anything uncertain, "moderate" allows warnings through
SCAN_IMAGES = True               # Set False to skip image scanning (faster but less safe)
MAX_IMAGE_SCANS_PER_RUN = 500    # Rate limit for Claude API calls per run
IMAGE_SCAN_BATCH_SIZE = 10       # Process images in batches
IMAGE_SCAN_DELAY = 1.0           # Seconds between batches
