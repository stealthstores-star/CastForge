#!/usr/bin/env python3
"""DSers Bulk Importer. Paste → OK → 2s → next. Check badge at end."""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

URLS_FILE = Path("dsers_import_urls.txt")

def main():
    urls = [l.strip() for l in URLS_FILE.read_text().splitlines() if l.strip().startswith("http")]
    print(f"\n  DSers Importer — {len(urls)} URLs\n")

    with sync_playwright() as pw:
        page = pw.chromium.launch(headless=False, channel="msedge",
            args=["--disable-blink-features=AutomationControlled"]) \
            .new_context(viewport={"width":1400,"height":900}).new_page()
        page.goto("https://www.dsers.com/application/import_list", wait_until="domcontentloaded", timeout=30000)
        input("  Log in if needed, then press ENTER... \n")

        t0 = time.time()
        for i, url in enumerate(urls):
            inp = page.query_selector('input[placeholder*="product link"]') or page.query_selector('input[type="text"]')
            if inp:
                inp.click(); inp.fill(""); inp.fill(url); time.sleep(0.2)
                btn = page.query_selector('button:has-text("OK")')
                btn.click() if btn else inp.press("Enter")
                time.sleep(2)
            if (i+1) % 25 == 0:
                print(f"  [{i+1}/{len(urls)}] {(i+1)/(time.time()-t0)*60:.0f}/min")

        page.reload(); time.sleep(3)
        badge = page.evaluate("""() => {
            const el = document.querySelector('a[href="/application/import_list"] b');
            return el ? parseInt(el.textContent.trim()) : -1;
        }""")
        elapsed = (time.time() - t0) / 60
        print(f"\n  Done. DSers badge: {badge} / {len(urls)}")
        if badge >= 0 and badge < len(urls):
            print(f"  Missing {len(urls) - badge} products. Re-run to fill gaps (DSers skips duplicates).")
        print(f"  Time: {elapsed:.0f} min\n")
        input("  Press ENTER to close... ")

if __name__ == "__main__": main()
