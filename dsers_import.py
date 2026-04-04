#!/usr/bin/env python3
"""DSers Bulk Importer. Batch of 25, reload, check badge, continue."""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

URLS_FILE = Path("dsers_import_urls.txt")
FAILED_FILE = Path("dsers_failed.txt")
BATCH = 25

def read_badge(page):
    return page.evaluate("""() => {
        const el = document.querySelector('a[href="/application/import_list"] b');
        return el ? parseInt(el.textContent.trim()) : -1;
    }""")

def main():
    urls = [l.strip() for l in URLS_FILE.read_text().splitlines() if l.strip().startswith("http")]
    print(f"\n  DSers Importer — {len(urls)} URLs, batches of {BATCH}\n")
    FAILED_FILE.unlink(missing_ok=True)
    failed_urls = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, channel="msedge",
            args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_context(viewport={"width":1400,"height":900}).new_page()
        page.goto("https://www.dsers.com/application/import_list", wait_until="domcontentloaded", timeout=30000)
        input("  Log in if needed, then press ENTER... ")

        page.reload(); time.sleep(3)
        start_badge = read_badge(page)
        print(f"  Starting badge: {start_badge}\n")
        if start_badge == -1:
            print("  ERROR: badge selector failed."); browser.close(); return

        t0 = time.time()
        total_expected = start_badge
        inp_sel = 'input[placeholder*="product link"]'

        for i, url in enumerate(urls):
            inp = page.query_selector(inp_sel) or page.query_selector('input[type="text"]')
            if not inp: continue
            inp.click(); inp.fill(""); inp.fill(url); time.sleep(0.2)
            btn = page.query_selector('button:has-text("OK")')
            btn.click() if btn else inp.press("Enter")
            time.sleep(2)
            total_expected += 1

            # Every BATCH URLs: reload and check badge
            if (i + 1) % BATCH == 0 or i == len(urls) - 1:
                page.reload(); time.sleep(3)
                badge = read_badge(page)
                diff = total_expected - badge if badge >= 0 else 0
                elapsed = time.time() - t0
                rate = (i + 1) / max(elapsed, 1) * 60
                print(f"  [{i+1}/{len(urls)}] badge={badge} expected={total_expected} missed={diff} | {rate:.0f}/min")
                if diff > 0:
                    # Log the batch range as failed
                    batch_start = (i + 1) - BATCH
                    for j in range(max(batch_start, 0), i + 1):
                        failed_urls.append(urls[j])
                    total_expected = badge  # reset expected to actual

        if failed_urls:
            FAILED_FILE.write_text("\n".join(failed_urls) + "\n")
            print(f"\n  {len(failed_urls)} URLs in failed batches → {FAILED_FILE}")
            print(f"  Retrying {len(failed_urls)} URLs...\n")
            total_expected = read_badge(page)
            for i, url in enumerate(failed_urls):
                inp = page.query_selector(inp_sel) or page.query_selector('input[type="text"]')
                if not inp: continue
                inp.click(); inp.fill(""); inp.fill(url); time.sleep(0.2)
                btn = page.query_selector('button:has-text("OK")')
                btn.click() if btn else inp.press("Enter")
                time.sleep(3)
                if (i + 1) % BATCH == 0 or i == len(failed_urls) - 1:
                    page.reload(); time.sleep(3)
                    print(f"  Retry [{i+1}/{len(failed_urls)}] badge={read_badge(page)}")

        final = read_badge(page)
        elapsed = time.time() - t0
        print(f"\n  DONE in {elapsed/60:.0f} min — badge: {final} (started at {start_badge}, +{final - start_badge})\n")
        input("  Press ENTER to close... "); browser.close()

if __name__ == "__main__": main()
