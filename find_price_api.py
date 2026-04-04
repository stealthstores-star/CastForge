"""Run this on your Mac to find the AliExpress price API endpoint.
Usage: python3 find_price_api.py
"""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(
        channel="msedge", headless=False,
        proxy={
            "server": "http://geo.iproyal.com:12321",
            "username": "jpo1c9lb5mytbj0t",
            "password": "GnXsjzZq15h0WEdY_country-us",
        },
    )
    context = browser.new_context(storage_state="ali_state.json")
    page = context.new_page()

    api_calls = []
    def on_response(response):
        url = response.url
        if response.status == 200:
            if any(x in url for x in [".js", ".css", ".png", ".jpg", ".gif", ".ico", ".woff", ".svg"]):
                return
            try:
                body = response.text()
                if "price" in body.lower()[:2000]:
                    api_calls.append(url)
                    print(f"PRICE API: {url[:150]} ({len(body)} bytes)")
            except:
                pass

    page.on("response", on_response)
    page.goto("https://www.aliexpress.com/item/3256806803054069.html")
    page.wait_for_timeout(10000)

    print(f"\nTotal price APIs: {len(api_calls)}")
    for u in api_calls:
        print(f"  {u[:150]}")

    input("\nPress Enter to close...")
    browser.close()
