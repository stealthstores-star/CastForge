#!/usr/bin/env python3
"""
DSers Bulk Importer — paste AliExpress URLs into DSers import list.
Auto-login, tracks imports via Ant Design badge count.
"""
import time
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

URLS_FILE = Path("dsers_import_urls.txt")
PROGRESS_FILE = Path("dsers_progress.txt")
FAILED_FILE = Path("dsers_failed.txt")
DSERS_IMPORT_PAGE = "https://www.dsers.com/app/import-list"
DSERS_EMAIL = "thetreasurehubllc@gmail.com"
DSERS_PASS = "Cococream1995!"

GET_COUNT_JS = """() => {
    const items = document.querySelectorAll('li.ant-menu-item, li.ant-menu-submenu, [class*="menu"] li, a[href*="import"]');
    for (const item of items) {
        if ((item.textContent || '').includes('Import list')) {
            const badge = item.querySelector('sup.ant-badge-count, .ant-badge-count, .ant-scroll-number-only-unit');
            if (badge) return parseInt(badge.textContent.trim()) || 0;
            const antBadge = item.querySelector('.ant-badge');
            if (antBadge) {
                const sup = antBadge.querySelector('sup');
                if (sup) return parseInt(sup.textContent.trim()) || 0;
            }
        }
    }
    return -1;
}"""


def load_urls():
    lines = URLS_FILE.read_text().strip().splitlines()
    return [l.strip() for l in lines if l.strip() and l.strip().startswith("http")]


def save_progress(n):
    PROGRESS_FILE.write_text(str(n))


def load_progress():
    if PROGRESS_FILE.exists():
        try:
            return int(PROGRESS_FILE.read_text().strip())
        except ValueError:
            pass
    return 0


def auto_login(page):
    """Auto-login to DSers if login form is showing."""
    time.sleep(2)
    # Check if we're on a login page
    url = page.url.lower()
    body = (page.query_selector("body").inner_text() or "").lower() if page.query_selector("body") else ""

    if "login" in url or "sign" in url or "email" in body and "password" in body:
        print("  Login form detected — auto-logging in...")
        try:
            # Fill email
            email_input = page.query_selector('input[type="email"], input[name="email"], input[placeholder*="email" i], input[placeholder*="Email"]')
            if email_input:
                email_input.click()
                email_input.fill(DSERS_EMAIL)
                time.sleep(0.3)

            # Fill password
            pass_input = page.query_selector('input[type="password"], input[name="password"]')
            if pass_input:
                pass_input.click()
                pass_input.fill(DSERS_PASS)
                time.sleep(0.3)

            # Click submit
            submit = page.query_selector('button[type="submit"], button:has-text("Log in"), button:has-text("Sign in"), button:has-text("Login")')
            if submit:
                submit.click()
            else:
                pass_input.press("Enter")

            print("  Submitted login, waiting for redirect...")
            time.sleep(5)

            # Wait for import list page to load
            for _ in range(10):
                if "import-list" in page.url.lower() or "import" in page.url.lower():
                    print("  Logged in!")
                    return True
                time.sleep(2)

            # Navigate to import list
            page.goto(DSERS_IMPORT_PAGE, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
            print("  Navigated to import list.")
            return True
        except Exception as e:
            print(f"  Auto-login failed: {e}")
            return False
    else:
        print("  Already logged in.")
        return True


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

        # Step 1: Login
        print("  Logging in to DSers...")
        page.goto("https://www.dsers.com/application/login", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        # Wait for login form
        page.wait_for_selector('input[type="password"]', timeout=10000)

        # Clear and fill email
        email_input = page.query_selector('input[type="text"]')
        email_input.click()
        email_input.fill("")
        email_input.fill(DSERS_EMAIL)
        time.sleep(0.3)

        # Clear and fill password
        pass_input = page.query_selector('input[type="password"]')
        pass_input.click()
        pass_input.fill("")
        pass_input.fill(DSERS_PASS)
        time.sleep(0.3)

        # Click LOG IN
        login_btn = page.query_selector('button:has-text("LOG IN")')
        if login_btn:
            login_btn.click()
        else:
            pass_input.press("Enter")

        # Wait for redirect away from login
        print("  Waiting for login redirect...")
        for _ in range(20):
            time.sleep(1)
            if "login" not in page.url.lower():
                break
        print(f"  Logged in! URL: {page.url[:60]}")

        # Step 2: Navigate to import list
        print("  Opening import list...")
        page.goto(DSERS_IMPORT_PAGE, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        # Test badge selector
        count = page.evaluate(GET_COUNT_JS)
        print(f"  Badge count: {count}")
        tracking = count >= 0
        if not tracking:
            print("  Badge selector returned -1 — running in simple mode (no tracking)\n")
        else:
            print(f"  Badge tracking active!\n")

        input_sel = 'input[placeholder*="product link"]'
        failed = []
        imported = 0
        done = start_from
        t0 = time.time()

        for i in range(start_from, len(urls)):
            url = urls[i]
            try:
                count_before = page.evaluate(GET_COUNT_JS) if tracking else -1

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

                if tracking and count_before >= 0:
                    success = False
                    for _ in range(10):
                        time.sleep(0.5)
                        count_after = page.evaluate(GET_COUNT_JS)
                        if count_after > count_before:
                            success = True
                            imported += 1
                            break
                    if not success:
                        failed.append(url)
                else:
                    time.sleep(2.5)
                    imported += 1

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
                cur = page.evaluate(GET_COUNT_JS) if tracking else "?"
                print(f"  [{done}/{len(urls)}] imported={imported} failed={len(failed)} badge={cur} | {rate:.0f}/min ETA {eta:.0f}m")
            elif done % 25 == 0:
                print(f"  [{done}/{len(urls)}] imported={imported} failed={len(failed)}")

        if failed:
            FAILED_FILE.write_text("\n".join(failed) + "\n")
            print(f"\n  {len(failed)} failed → {FAILED_FILE}")

        # Retry with 8s wait
        if failed:
            print(f"\n  ── Retry: {len(failed)} URLs ──\n")
            still_failed = []
            for j, url in enumerate(failed):
                try:
                    count_before = page.evaluate(GET_COUNT_JS) if tracking else -1
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
                    if tracking and count_before >= 0:
                        success = False
                        for _ in range(16):
                            time.sleep(0.5)
                            if page.evaluate(GET_COUNT_JS) > count_before:
                                success = True
                                imported += 1
                                break
                        if not success:
                            still_failed.append(url)
                    else:
                        time.sleep(3)
                        imported += 1
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
        final = page.evaluate(GET_COUNT_JS) if tracking else "?"
        print(f"\n  Done! {done}/{len(urls)} in {elapsed/60:.0f} min")
        print(f"  Imported: {imported}, Failed: {len(failed)}, Badge: {final}\n")
        input("  Press ENTER to close browser... ")
        browser.close()


if __name__ == "__main__":
    main()
