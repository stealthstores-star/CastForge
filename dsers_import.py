#!/usr/bin/env python3
"""DSers Bulk Importer. Reads dsers_import_urls.txt, pastes into DSers."""
import time, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

URLS_FILE = Path("dsers_import_urls.txt")
FAILED_FILE = Path("dsers_failed.txt")

def read_count(page):
    return page.evaluate("""() => {
        const el = document.querySelector('a[href="/application/import_list"] b');
        return el ? parseInt(el.textContent.trim()) : -1;
    }""")

def submit_url(page, url, wait=5):
    before = read_count(page)
    inp = page.query_selector('input[placeholder*="product link"]') or page.query_selector('input[type="text"]')
    if not inp: return False
    inp.click(); inp.fill(""); inp.fill(url); time.sleep(0.2)
    btn = page.query_selector('button:has-text("OK")')
    btn.click() if btn else inp.press("Enter")
    for _ in range(wait * 2):
        time.sleep(0.5)
        if read_count(page) > before: return True
    return False

def run_batch(page, urls, wait=5):
    failed, ok = [], 0
    t0 = time.time()
    for i, url in enumerate(urls):
        if submit_url(page, url, wait): ok += 1
        else: failed.append(url)
        if (i+1) % 25 == 0:
            el = time.time() - t0; rate = (i+1)/max(el,1)*60
            print(f"  [{i+1}/{len(urls)}] DSers count: {read_count(page)} | success={ok} failed={len(failed)} | {rate:.0f}/min")
    return failed, ok

def main():
    urls = [l.strip() for l in URLS_FILE.read_text().splitlines() if l.strip().startswith("http")]
    print(f"\n  DSers Importer — {len(urls)} URLs\n")
    FAILED_FILE.unlink(missing_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, channel="msedge",
            args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_context(viewport={"width":1400,"height":900}).new_page()
        page.goto("https://www.dsers.com/application/import_list", wait_until="domcontentloaded", timeout=30000)
        input("  Log in if needed, then press ENTER... ")

        count = read_count(page)
        print(f"  Badge count: {count}\n")
        if count == -1:
            print("  ERROR: can't read badge. Check selector."); browser.close(); return

        failed, ok = run_batch(page, urls)
        print(f"\n  Pass 1 done: {ok} success, {len(failed)} failed, badge={read_count(page)}")

        if failed:
            FAILED_FILE.write_text("\n".join(failed) + "\n")
            print(f"\n  Retrying {len(failed)} failed URLs (4s wait)...\n")
            still_failed, ok2 = run_batch(page, failed, wait=4)
            ok += ok2
            if still_failed:
                FAILED_FILE.write_text("\n".join(still_failed) + "\n")
                print(f"  {len(still_failed)} still failed → {FAILED_FILE}")
            else:
                FAILED_FILE.unlink(missing_ok=True)
                print(f"  All retries succeeded!")

        print(f"\n  DONE: {ok} imported, {len(failed)} failed, DSers badge: {read_count(page)}\n")
        input("  Press ENTER to close... "); browser.close()

if __name__ == "__main__": main()
