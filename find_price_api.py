"""Run on Mac: python3 find_price_api.py
Opens Edge WITHOUT proxy, uses login state, logs all API responses with price data.
"""
from playwright.sync_api import sync_playwright
import re

with sync_playwright() as p:
    print("Launching Edge (no proxy, direct connection)...")
    browser = p.chromium.launch(channel="msedge", headless=False)

    try:
        context = browser.new_context(storage_state="ali_state.json")
        print("Loaded login state from ali_state.json")
    except Exception:
        context = browser.new_context()
        print("No login state — fresh context")

    page = context.new_page()

    api_calls = []
    all_responses = []

    def on_response(response):
        url = response.url
        # Skip static assets
        if any(x in url for x in [".js", ".css", ".png", ".jpg", ".gif", ".ico",
                                    ".woff", ".svg", ".webp", ".avif", "google",
                                    "facebook", "criteo", "beacon"]):
            return
        try:
            body = response.text()
            if len(body) > 200:
                has_price = "price" in body.lower()[:5000]
                all_responses.append({"url": url[:100], "len": len(body), "has_price": has_price})
                if has_price:
                    api_calls.append({"url": url, "len": len(body)})
                    print(f"\n*** PRICE API ***")
                    print(f"  URL: {url[:150]}")
                    print(f"  Size: {len(body)} bytes")
                    matches = re.findall(r'"(?:min|formatted|activity|discount|sku|act).*?[Pp]rice.*?"[^,]{0,80}', body[:5000])
                    if matches:
                        print(f"  Fields: {matches[:5]}")
        except Exception:
            pass

    page.on("response", on_response)

    url = "https://www.aliexpress.com/item/3256806803054069.html"
    print(f"\nNavigating to {url}...")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        print("Loaded. Waiting 10s for JS to fetch prices...")
        page.wait_for_timeout(10000)
    except Exception as e:
        print(f"Error: {e}")
        page.wait_for_timeout(5000)

    print(f"\n{'='*50}")
    print(f"Price APIs found: {len(api_calls)}")
    for a in api_calls:
        print(f"  {a['url'][:120]} ({a['len']} bytes)")
    print(f"\nAll non-static responses ({len(all_responses)}):")
    for r in all_responses[:20]:
        flag = " <-- HAS PRICE" if r["has_price"] else ""
        print(f"  [{r['len']:>6} bytes] {r['url']}{flag}")
    print(f"{'='*50}")

    input("\nPress Enter to close...")
    browser.close()
