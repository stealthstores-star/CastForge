#!/usr/bin/env python3
"""
DSers Bulk Importer — paste AliExpress URLs into DSers import list.

Usage:
    python3 dsers_import.py

Reads dsers_import_urls.txt. Watches the sidebar "Import list" badge count
to verify each import. Failed URLs saved to dsers_failed.txt and retried.
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


def get_import_count(page):
    """Read the number next to 'Import list' in the sidebar."""
    try:
        count = page.evaluate("""() => {
            // Find the sidebar link that contains "Import list"
            const links = document.querySelectorAll('a, li, div, span');
            for (const el of links) {
                const text = el.textContent || '';
                if (text.includes('Import list')) {
                    // Find the badge/number element inside or next to it
                    const badges = el.querySelectorAll('span, em, b, strong, [class*="badge"], [class*="count"], [class*="num"]');
                    for (const b of badges) {
                        const t = b.textContent.trim();
                        if (/^\d+$/.test(t)) return parseInt(t);
                    }
                    // Try: the number might be directly in the text
                    const m = text.match(/Import list\\s*(\\d+)/);
                    if (m) return parseInt(m[1]);
                }
            }
            // Broader: any element right after "Import list" text
            const all = document.body.innerText;
            const m = all.match(/Import list\\s*(\\d+)/);
            if (m) return parseInt(m[1]);
            return -1;
        }""")
        return count
    except Exception:
        return -1


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

        # Read initial count to verify selector works
        initial = get_import_count(page)
        print(f"  Current import list count: {initial}")
        if initial == -1:
            print("  WARNING: Can't read badge count. Will try anyway.\n")
        else:
            print()

        input_sel = 'input[placeholder*="product link"]'
        failed = []
        done = start_from
        imported = 0
        t0 = time.time()

        for i in range(start_from, len(urls)):
            url = urls[i]

            try:
                count_before = get_import_count(page)

                # Find input, paste URL, click OK
                inp = page.query_selector(input_sel) or \
                      page.query_selector('input[placeholder*="link"]') or \
                      page.query_selector('input[type="text"]')
                if not inp:
                    failed.append(url)
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

                # Wait up to 5s for count to go up by 1
                success = False
                if count_before >= 0:
                    for _ in range(10):
                        time.sleep(0.5)
                        count_after = get_import_count(page)
                        if count_after > count_before:
                            success = True
                            imported += 1
                            break
                else:
                    # Can't read count, just wait 2s and assume ok
                    time.sleep(2)
                    success = True
                    imported += 1

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
                rate = (done - start_from) / max(elapsed, 1) * 60
                remaining = len(urls) - done
                eta = remaining / max(rate, 0.1)
                cur = get_import_count(page)
                print(f"  [{done}/{len(urls)}] imported={imported} failed={len(failed)} badge={cur} | {rate:.0f}/min ETA {eta:.0f}m")
            elif done % 25 == 0:
                print(f"  [{done}/{len(urls)}] imported={imported} failed={len(failed)}")

        # Save failed
        if failed:
            FAILED_FILE.write_text("\n".join(failed) + "\n")
            print(f"\n  {len(failed)} failed URLs → {FAILED_FILE}")

        # Retry pass
        if failed:
            print(f"\n  ── Retry pass: {len(failed)} URLs ──\n")
            retry_failed = []
            for j, url in enumerate(failed):
                try:
                    count_before = get_import_count(page)

                    inp = page.query_selector(input_sel) or \
                          page.query_selector('input[placeholder*="link"]')
                    if not inp:
                        retry_failed.append(url)
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

                    # Longer wait on retry — 8 seconds
                    success = False
                    if count_before >= 0:
                        for _ in range(16):
                            time.sleep(0.5)
                            if get_import_count(page) > count_before:
                                success = True
                                imported += 1
                                break
                    else:
                        time.sleep(3)
                        success = True

                    if not success:
                        retry_failed.append(url)
                except Exception:
                    retry_failed.append(url)

                if (j + 1) % 25 == 0:
                    print(f"  Retry [{j+1}/{len(failed)}]")

            if retry_failed:
                FAILED_FILE.write_text("\n".join(retry_failed) + "\n")
                print(f"  {len(retry_failed)} still failed → {FAILED_FILE}")
            else:
                FAILED_FILE.unlink(missing_ok=True)
                print(f"  All retries succeeded!")

        elapsed = time.time() - t0
        final = get_import_count(page)
        print(f"\n  Done! {done}/{len(urls)} processed in {elapsed/60:.0f} min")
        print(f"  Imported: {imported}, Failed: {len(failed)}, Badge: {final}\n")
        input("  Press ENTER to close browser... ")
        browser.close()


if __name__ == "__main__":
    main()
