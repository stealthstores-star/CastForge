#!/usr/bin/env python3
"""
DSers Bulk Importer — paste AliExpress URLs into DSers import list.

Usage:
    python3 dsers_import.py

Reads URLs from dsers_import_urls.txt, resumes from dsers_progress.txt.
Opens Edge so you can log into DSers first.
Waits for import list count to increment before moving to next URL.
Restarting from 0 is safe — DSers rejects duplicates.
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


def get_import_count(page):
    """Read the badge number next to 'Import list' in the DSers sidebar."""
    try:
        # Try multiple selectors for the badge count
        for sel in [
            '.ant-badge-count',
            '[class*="badge"] [class*="count"]',
            '[class*="import"] .ant-badge-count',
            '.ant-scroll-number-only-unit.current',
        ]:
            els = page.query_selector_all(sel)
            for el in els:
                txt = (el.inner_text() or "").strip()
                if txt.isdigit():
                    return int(txt)
        # Fallback: read the badge via JS
        count = page.evaluate("""() => {
            const badges = document.querySelectorAll('.ant-badge-count, [class*="badge"]');
            for (const b of badges) {
                const n = parseInt(b.textContent.trim());
                if (!isNaN(n) && n > 0) return n;
            }
            return -1;
        }""")
        if count >= 0:
            return count
    except Exception:
        pass
    return -1


def main():
    if not URLS_FILE.exists():
        print(f"  {URLS_FILE} not found.")
        sys.exit(1)

    urls = load_urls()

    # Reset progress to 0 — dedup handles already-imported URLs
    save_progress(0)
    start_from = 0

    print(f"\n══════════════════════════════════════")
    print(f"  DSers Bulk Importer")
    print(f"══════════════════════════════════════")
    print(f"  URLs: {len(urls)}")
    print(f"  Starting from: {start_from}")
    print(f"  Duplicates will be skipped by DSers\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False, channel="msedge",
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = ctx.new_page()

        print("  Opening DSers import page...")
        print("  Log into DSers if needed, then press ENTER here.\n")
        page.goto(DSERS_IMPORT_PAGE, wait_until="domcontentloaded", timeout=30000)
        input("  >>> Press ENTER when DSers import list page is loaded... ")

        done = start_from
        imported = 0
        skipped = 0
        errors = 0
        t0 = time.time()

        input_sel = 'input[placeholder*="product link"]'

        for i in range(start_from, len(urls)):
            url = urls[i]

            try:
                # Get current count before submitting
                count_before = get_import_count(page)

                # Find input field
                page.wait_for_selector(input_sel, timeout=10000)
                inp = page.query_selector(input_sel)
                if not inp:
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

                # Click OK
                ok_btn = page.query_selector('button:has-text("OK")') or \
                         page.query_selector('button:has-text("Ok")')
                if ok_btn:
                    ok_btn.click()
                else:
                    inp.press("Enter")

                # Wait for count to increment (up to 5 seconds)
                success = False
                for _ in range(10):
                    time.sleep(0.5)
                    count_after = get_import_count(page)

                    # Check for error toasts / messages
                    try:
                        toast = page.query_selector('.ant-message-error, .ant-notification-notice-error')
                        if toast and toast.is_visible():
                            msg = (toast.inner_text() or "").strip()[:80]
                            if "exist" in msg.lower() or "already" in msg.lower() or "duplicate" in msg.lower():
                                skipped += 1
                                success = True  # duplicate = skip, not error
                                break
                    except Exception:
                        pass

                    if count_before >= 0 and count_after > count_before:
                        imported += 1
                        success = True
                        break

                if not success:
                    # Check if it was a rate limit
                    try:
                        body = (page.query_selector("body").inner_text() or "")[:500].lower()
                        if any(w in body for w in ["rate limit", "too many", "try again"]):
                            errors += 1
                            print(f"  [{i+1}] Rate limited — waiting 30s...")
                            time.sleep(30)
                            # Retry
                            inp = page.query_selector(input_sel)
                            if inp:
                                inp.click(); inp.fill(""); inp.fill(url)
                                time.sleep(0.3)
                                ok_btn = page.query_selector('button:has-text("OK")')
                                if ok_btn: ok_btn.click()
                                else: inp.press("Enter")
                                time.sleep(3)
                                count_retry = get_import_count(page)
                                if count_before >= 0 and count_retry > count_before:
                                    imported += 1
                                    success = True
                    except Exception:
                        pass

                    if not success:
                        errors += 1
                        print(f"  [{i+1}] FAILED — count didn't increment ({count_before}→{get_import_count(page)}) — {url[-40:]}")

                done = i + 1
                save_progress(done)

                # Progress
                if done % 50 == 0:
                    elapsed = time.time() - t0
                    rpm = done / max(elapsed, 1) * 60
                    remaining = len(urls) - done
                    eta = remaining / max(rpm, 0.1)
                    cur_count = get_import_count(page)
                    print(f"  [{done}/{len(urls)}] imported={imported} skipped={skipped} errors={errors} badge={cur_count} | {rpm:.0f}/min ETA {eta:.0f}m")

            except Exception as e:
                errors += 1
                print(f"  [{i+1}] Error: {type(e).__name__}: {str(e)[:80]}")
                if "closed" in str(e).lower() or "crashed" in str(e).lower():
                    print("  Browser closed — run again to resume.")
                    save_progress(i)
                    sys.exit(1)
                time.sleep(5)

        save_progress(done)
        elapsed = time.time() - t0
        final_count = get_import_count(page)
        print(f"\n  Done! {done}/{len(urls)} processed in {elapsed/60:.0f} min")
        print(f"  Imported: {imported}, Skipped (dupes): {skipped}, Errors: {errors}")
        print(f"  DSers badge count: {final_count}\n")

        input("  Press ENTER to close browser... ")
        browser.close()


if __name__ == "__main__":
    main()
