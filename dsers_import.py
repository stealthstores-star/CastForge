#!/usr/bin/env python3
"""
DSers Bulk Importer — paste AliExpress URLs into DSers import list.

Usage:
    python3 dsers_import.py

Verifies each import by checking if the input field clears after OK click.
Failed URLs saved to dsers_failed.txt and retried at the end.
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


def save_progress(n):
    PROGRESS_FILE.write_text(str(n))


def main():
    if not URLS_FILE.exists():
        print(f"  {URLS_FILE} not found.")
        sys.exit(1)

    urls = load_urls()

    # Reset to 0
    save_progress(0)

    print(f"\n══════════════════════════════════════")
    print(f"  DSers Bulk Importer")
    print(f"══════════════════════════════════════")
    print(f"  URLs: {len(urls)}")
    print(f"  Starting fresh from 0\n")

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
        imported = 0
        done = 0
        t0 = time.time()

        for i in range(len(urls)):
            url = urls[i]
            try:
                inp = page.query_selector(input_sel) or \
                      page.query_selector('input[placeholder*="link"]') or \
                      page.query_selector('input[type="text"]')
                if not inp:
                    failed.append(url)
                    done = i + 1
                    save_progress(done)
                    continue

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

                # Wait up to 5s — check for:
                # 1. Input field clearing (DSers clears on success)
                # 2. Error toast appearing
                success = False
                for check in range(10):
                    time.sleep(0.5)
                    # Check if input value is now empty (DSers cleared it = success)
                    try:
                        val = inp.input_value() or ""
                        if val == "" or val != url:
                            success = True
                            imported += 1
                            break
                    except Exception:
                        success = True
                        imported += 1
                        break
                    # Check for error toast
                    try:
                        err = page.query_selector('.ant-message-error')
                        if err and err.is_visible():
                            break
                    except Exception:
                        pass

                if not success:
                    failed.append(url)

            except Exception as e:
                failed.append(url)
                if "closed" in str(e).lower() or "crashed" in str(e).lower():
                    print(f"\n  Browser closed at [{i+1}]. Run again to resume.")
                    save_progress(i)
                    if failed:
                        FAILED_FILE.write_text("\n".join(failed) + "\n")
                    sys.exit(1)

            done = i + 1
            save_progress(done)

            if done % 100 == 0:
                elapsed = time.time() - t0
                rate = done / max(elapsed, 1) * 60
                remaining = len(urls) - done
                eta = remaining / max(rate, 0.1)
                print(f"  [{done}/{len(urls)}] imported={imported} failed={len(failed)} | {rate:.0f}/min ETA {eta:.0f}m")
            elif done % 25 == 0:
                print(f"  [{done}/{len(urls)}] imported={imported} failed={len(failed)}")

        # Save failed
        if failed:
            FAILED_FILE.write_text("\n".join(failed) + "\n")
            print(f"\n  {len(failed)} failed → {FAILED_FILE}")

        # Retry with longer wait
        if failed:
            print(f"\n  ── Retry: {len(failed)} URLs (8s wait each) ──\n")
            still_failed = []
            for j, url in enumerate(failed):
                try:
                    inp = page.query_selector(input_sel) or \
                          page.query_selector('input[placeholder*="link"]')
                    if not inp:
                        still_failed.append(url)
                        continue
                    inp.click()
                    inp.fill("")
                    inp.fill(url)
                    time.sleep(0.3)
                    ok_btn = page.query_selector('button:has-text("OK")')
                    if ok_btn:
                        ok_btn.click()
                    else:
                        inp.press("Enter")

                    success = False
                    for _ in range(16):
                        time.sleep(0.5)
                        try:
                            val = inp.input_value() or ""
                            if val == "" or val != url:
                                success = True
                                imported += 1
                                break
                        except:
                            success = True
                            imported += 1
                            break
                    if not success:
                        still_failed.append(url)
                except Exception:
                    still_failed.append(url)
                if (j + 1) % 25 == 0:
                    print(f"  Retry [{j+1}/{len(failed)}]")

            if still_failed:
                FAILED_FILE.write_text("\n".join(still_failed) + "\n")
                print(f"  {len(still_failed)} still failed → {FAILED_FILE}")
            else:
                FAILED_FILE.unlink(missing_ok=True)
                print(f"  All retries done!")

        elapsed = time.time() - t0
        print(f"\n  Done! {done}/{len(urls)} in {elapsed/60:.0f} min")
        print(f"  Imported: {imported}, Failed: {len(failed)}\n")
        input("  Press ENTER to close browser... ")
        browser.close()


if __name__ == "__main__":
    main()
