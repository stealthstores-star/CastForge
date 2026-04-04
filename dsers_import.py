#!/usr/bin/env python3
"""
DSers Bulk Importer — paste AliExpress URLs into DSers import list.

Usage:
    python3 dsers_import.py

Reads dsers_import_urls.txt, pastes each URL, clicks OK, waits 2s, next.
Saves failed URLs to dsers_failed.txt and retries them at the end.
Resumes from dsers_progress.txt if interrupted.
"""
import time
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

URLS_FILE = Path("dsers_import_urls.txt")
PROGRESS_FILE = Path("dsers_progress.txt")
FAILED_FILE = Path("dsers_failed.txt")
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
        print(f"  {URLS_FILE} not found.")
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

        print("  Opening DSers import page...")
        print("  Log into DSers if needed, then press ENTER here.\n")
        page.goto(DSERS_IMPORT_PAGE, wait_until="domcontentloaded", timeout=30000)
        input("  >>> Press ENTER when DSers import list page is loaded... ")

        input_sel = 'input[placeholder*="product link"]'
        failed = []
        done = start_from
        t0 = time.time()

        def process_url(url):
            """Paste URL, click OK, wait 2s. Returns True unless actual error."""
            inp = page.query_selector(input_sel) or \
                  page.query_selector('input[placeholder*="link"]') or \
                  page.query_selector('input[type="text"]')
            if not inp:
                return False

            inp.click()
            inp.fill("")
            inp.fill(url)
            time.sleep(0.3)

            ok_btn = page.query_selector('button:has-text("OK")') or \
                     page.query_selector('button:has-text("Ok")')
            if ok_btn:
                ok_btn.click()
            else:
                inp.press("Enter")

            time.sleep(2)

            # Only count as failed if there's a visible error toast
            try:
                toast = page.query_selector('.ant-message-error, .ant-notification-notice-error, [class*="error-toast"]')
                if toast and toast.is_visible():
                    msg = (toast.inner_text() or "").strip()[:80]
                    # "already exists" = duplicate, not a real error
                    if "exist" in msg.lower() or "already" in msg.lower():
                        return True
                    return False
            except Exception:
                pass

            return True

        # Main pass
        for i in range(start_from, len(urls)):
            url = urls[i]
            try:
                ok = process_url(url)
                if not ok:
                    failed.append(url)
            except Exception as e:
                failed.append(url)
                if "closed" in str(e).lower() or "crashed" in str(e).lower():
                    print(f"\n  Browser closed at [{i+1}]. Run again to resume.")
                    save_progress(i)
                    FAILED_FILE.write_text("\n".join(failed) + "\n")
                    sys.exit(1)

            done = i + 1
            save_progress(done)

            if done % 100 == 0:
                elapsed = time.time() - t0
                rate = (done - start_from) / max(elapsed, 1) * 60
                remaining = len(urls) - done
                eta = remaining / max(rate, 0.1)
                print(f"  [{done}/{len(urls)}] {rate:.0f}/min | ETA {eta:.0f}m | failed={len(failed)}")
            elif done % 25 == 0:
                print(f"  [{done}/{len(urls)}]")

        # Save failed
        if failed:
            FAILED_FILE.write_text("\n".join(failed) + "\n")
            print(f"\n  {len(failed)} failed URLs saved to {FAILED_FILE}")

        # Retry pass
        if failed:
            print(f"\n  ── Retry pass: {len(failed)} URLs ──\n")
            retry_failed = []
            for j, url in enumerate(failed):
                try:
                    ok = process_url(url)
                    if not ok:
                        retry_failed.append(url)
                except Exception:
                    retry_failed.append(url)

                if (j + 1) % 25 == 0:
                    print(f"  Retry [{j+1}/{len(failed)}]")

            if retry_failed:
                FAILED_FILE.write_text("\n".join(retry_failed) + "\n")
                print(f"  {len(retry_failed)} still failed after retry → {FAILED_FILE}")
            else:
                FAILED_FILE.unlink(missing_ok=True)
                print(f"  All retries succeeded!")

        elapsed = time.time() - t0
        print(f"\n  Done! {done}/{len(urls)} processed in {elapsed/60:.0f} min\n")
        input("  Press ENTER to close browser... ")
        browser.close()


if __name__ == "__main__":
    main()
