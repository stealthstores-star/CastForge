#!/usr/bin/env python3
"""
DSers Bulk Importer — paste AliExpress URLs into DSers import list.

Usage:
    python3 dsers_import.py

Reads URLs from dsers_import_urls.txt, resumes from dsers_progress.txt.
Opens Edge so you can log into DSers first.
"""
import time
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

URLS_FILE = Path("dsers_import_urls.txt")
PROGRESS_FILE = Path("dsers_progress.txt")
DSERS_IMPORT_PAGE = "https://www.dsers.com/app/import-list"


def load_urls():
    lines = URLS_FILE.read_text().strip().splitlines()
    return [l.strip() for l in lines if l.strip() and l.strip().startswith("http")]


def load_progress():
    if PROGRESS_FILE.exists():
        try:
            return int(PROGRESS_FILE.read_text().strip())
        except ValueError:
            pass
    return 0


def save_progress(n):
    PROGRESS_FILE.write_text(str(n))


def main():
    if not URLS_FILE.exists():
        print(f"  {URLS_FILE} not found. Run: python3 main.py export-urls")
        sys.exit(1)

    urls = load_urls()
    start_from = load_progress()

    print(f"\n══════════════════════════════════════")
    print(f"  DSers Bulk Importer")
    print(f"══════════════════════════════════════")
    print(f"  URLs: {len(urls)}")
    print(f"  Resuming from: {start_from}")
    print(f"  Remaining: {len(urls) - start_from}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False, channel="msedge",
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = ctx.new_page()

        # Navigate to DSers
        print("  Opening DSers import page...")
        print("  Log into DSers if needed, then press ENTER here.\n")
        page.goto(DSERS_IMPORT_PAGE, wait_until="domcontentloaded", timeout=30000)
        input("  >>> Press ENTER when DSers import list page is loaded... ")

        done = start_from
        errors = 0
        t0 = time.time()

        for i in range(start_from, len(urls)):
            url = urls[i]

            try:
                # Find the input field
                input_sel = 'input[placeholder*="product link"]'
                page.wait_for_selector(input_sel, timeout=10000)
                inp = page.query_selector(input_sel)
                if not inp:
                    # Broader fallback
                    inp = page.query_selector('input[placeholder*="link"]') or \
                          page.query_selector('input[type="text"]')
                if not inp:
                    print(f"  [{i+1}] Can't find input field — waiting 10s...")
                    time.sleep(10)
                    continue

                # Clear and paste URL
                inp.click()
                inp.fill("")
                inp.fill(url)
                time.sleep(0.3)

                # Click OK button
                ok_btn = page.query_selector('button:has-text("OK")') or \
                         page.query_selector('button:has-text("Ok")') or \
                         page.query_selector('button:has-text("ok")')
                if ok_btn:
                    ok_btn.click()
                else:
                    # Try pressing Enter
                    inp.press("Enter")

                # Wait for response
                time.sleep(1.5)

                # Check for errors / rate limiting
                body = (page.query_selector("body").inner_text() or "").lower()
                if any(w in body for w in ["rate limit", "too many", "try again later", "error"]):
                    err_msg = [w for w in ["rate limit", "too many", "try again later"] if w in body]
                    if err_msg:
                        errors += 1
                        print(f"  [{i+1}] Rate limited — waiting 30s... ({err_msg[0]})")
                        time.sleep(30)
                        # Retry this URL
                        inp = page.query_selector(input_sel)
                        if inp:
                            inp.click()
                            inp.fill("")
                            inp.fill(url)
                            time.sleep(0.3)
                            ok_btn = page.query_selector('button:has-text("OK")')
                            if ok_btn:
                                ok_btn.click()
                            else:
                                inp.press("Enter")
                            time.sleep(1.5)

                done = i + 1
                save_progress(done)

                # Progress
                if done % 100 == 0:
                    elapsed = time.time() - t0
                    rate = done - start_from
                    rpm = rate / max(elapsed, 1) * 60
                    remaining = len(urls) - done
                    eta = remaining / max(rpm, 0.1)
                    print(f"  [{done}/{len(urls)}] {rate} imported | {rpm:.0f}/min | ETA {eta:.0f}m | errors={errors}")
                elif done % 25 == 0:
                    print(f"  [{done}/{len(urls)}]")

            except Exception as e:
                errors += 1
                print(f"  [{i+1}] Error: {type(e).__name__}: {str(e)[:80]}")
                if "closed" in str(e).lower() or "crashed" in str(e).lower():
                    print("  Browser closed — exiting. Run again to resume.")
                    save_progress(done)
                    sys.exit(1)
                time.sleep(5)

        save_progress(done)
        elapsed = time.time() - t0
        print(f"\n  Done! {done}/{len(urls)} imported in {elapsed/60:.0f} minutes, {errors} errors\n")

        input("  Press ENTER to close browser... ")
        browser.close()


if __name__ == "__main__":
    main()
