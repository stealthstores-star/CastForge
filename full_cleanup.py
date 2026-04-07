#!/usr/bin/env python3
"""
CastForge Full Cleanup — 4-phase product pipeline.
Phase 1: Delete 0-image products
Phase 2: Delete bad-image products (AI vision, 6 workers)
Phase 3: Re-categorise products
Phase 4: Pull AliExpress reviews

Usage:
    python3 full_cleanup.py --dry-run --phase 1     # Test phase 1
    python3 full_cleanup.py --dry-run                # Test all phases
    python3 full_cleanup.py                          # Full run all phases
    python3 full_cleanup.py --phase 2                # Run only phase 2
"""
import json, random, re, signal, sys, time, threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests as http
import config
from categorizer import categorize
from uploader import get_shopify_token

# ── Files ──
PROGRESS_FILE = Path("cleanup_progress.json")
COLLECTION_MAP_FILE = Path("collection_map.json")
CHECKPOINT_FILE = Path("scrape_checkpoint.json")
PUSHED_TITLES_FILE = Path("pushed_titles.json")
ALI_STATE_FILE = Path("ali_state.json")

PHASE2_PROMPT = """Is this image a photograph of a physical model, figure, vehicle, terrain piece, or model accessory? Answer NO ONLY if the image is clearly: a smiley face emoji, cartoon clipart, generic stock photo unrelated to models, pure text, or a blank/placeholder image. Answer YES for any photograph of a real physical product even if it has watermarks, brand stamps, or banner overlays — those are still real products. Answer ONLY 'YES' or 'NO'."""

_file_lock = threading.Lock()
_shutdown = threading.Event()

def _handle_sigint(sig, frame):
    print("\n  Ctrl+C — saving progress and exiting...")
    _shutdown.set()
signal.signal(signal.SIGINT, _handle_sigint)

# ── Shopify helpers ──
def _headers(token):
    return {"Content-Type": "application/json", "X-Shopify-Access-Token": token}

def _base():
    return f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

def fetch_all_products(token, fields="id,title,images,tags,status", statuses=None):
    if statuses is None:
        statuses = ["active"]  # Only active by default — don't touch drafts
    headers = _headers(token)
    products = []
    for status in statuses:
        # Get expected count first
        cr = http.get(f"{_base()}/products/count.json?status={status}", headers=headers, timeout=15)
        expected = cr.json().get("count", "?") if cr.status_code == 200 else "?"
        print(f"    Shopify reports {expected} {status} products")

        url = f"{_base()}/products.json?limit=250&fields={fields}&status={status}"
        status_count = 0
        while url:
            for attempt in range(3):
                try:
                    r = http.get(url, headers=headers, timeout=30)
                    if r.status_code == 429:
                        time.sleep(float(r.headers.get("Retry-After", 2)))
                        continue
                    break
                except Exception:
                    time.sleep(2)
            else:
                break
            if r.status_code != 200:
                print(f"    API error {r.status_code}")
                break
            batch = r.json().get("products", [])
            products.extend(batch)
            status_count += len(batch)
            if len(products) % 1000 < 250:
                print(f"    ...{len(products)} fetched", flush=True)

            # Parse Link header for next page — handle rel="previous" safely
            url = None
            link = r.headers.get("Link", "")
            if link:
                # Split on >, < boundaries not commas (URLs can contain commas)
                for part in link.split(", <"):
                    if 'rel="next"' in part:
                        url = part.split(">")[0].lstrip("<")
                        break
            time.sleep(0.5)

        print(f"    Fetched {status_count} {status} products (expected {expected})")
    return products

def delete_product(pid, token):
    for _ in range(3):
        r = http.delete(f"{_base()}/products/{pid}.json", headers=_headers(token), timeout=15)
        if r.status_code in (200, 204): return True
        if r.status_code == 429: time.sleep(float(r.headers.get("Retry-After", 2))); continue
        break
    return False

# ── Progress ──
def load_progress():
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {"phase1_done": [], "phase2_done": [], "phase3_done": [], "phase4_done": [],
            "phase1_deleted": [], "phase2_deleted": [], "phase3_moved": [], "phase4_reviews": []}

def save_progress(prog):
    with _file_lock:
        PROGRESS_FILE.write_text(json.dumps(prog, indent=2, ensure_ascii=False))

# ── Phase 1: Delete 0-image products ──
def phase1(products, token, prog, dry_run):
    print(f"\n  ══ Phase 1: Delete 0-image products ══")
    done_set = set(prog["phase1_done"])
    zero = [p for p in products if len(p.get("images", [])) == 0 and p["id"] not in done_set]
    print(f"  {len(zero)} products with 0 images\n")
    deleted = 0
    for i, p in enumerate(zero):
        if _shutdown.is_set() or deleted >= 500:
            if deleted >= 500: print(f"  ⚠ SAFETY: 500 deletions. Halting Phase 1.")
            break
        pid, title = p["id"], p.get("title", "")[:60]
        if dry_run:
            print(f"  [P1] [{i+1}/{len(zero)}] 🗑 WOULD DELETE: {title}")
        else:
            if delete_product(pid, token):
                deleted += 1
                prog["phase1_deleted"].append({"id": pid, "title": title})
                print(f"  [P1] [{i+1}/{len(zero)}] 🗑 DELETED: {title}")
            time.sleep(0.3)
        prog["phase1_done"].append(pid)
        save_progress(prog)
    print(f"  Phase 1 done: {deleted} deleted")
    return deleted

# ── Phase 2: Vision classify + delete bad images ──
def phase2(products, token, prog, dry_run, test_count=0):
    print(f"\n  ══ Phase 2: {'TEST' if test_count else 'Delete'} bad-image products (AI vision) ══")
    api_key = config.ANTHROPIC_API_KEY
    done_set = set(prog["phase2_done"])
    with_img = [p for p in products if len(p.get("images", [])) > 0 and p["id"] not in done_set]
    if test_count:
        with_img = with_img[:test_count]
        print(f"  TEST MODE: classifying {len(with_img)} products (no deletions)\n")
    else:
        print(f"  {len(with_img)} products to classify (~{len(with_img)*5//60} min @ 6 workers)\n")
    deleted, kept = [0], [0]
    t0 = time.time()

    def classify_one(item):
        i, p = item
        if _shutdown.is_set() or deleted[0] >= 50: return
        pid, title = p["id"], p.get("title", "")[:60]
        img_url = p["images"][0].get("src", "")
        try:
            dl = http.get(img_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if dl.status_code != 200 or len(dl.content) < 500:
                return
            from PIL import Image; from io import BytesIO; import base64
            img = Image.open(BytesIO(dl.content)).convert("RGB")
            img.thumbnail((512, 512))
            buf = BytesIO(); img.save(buf, format="JPEG", quality=80)
            b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
        except Exception:
            return

        try:
            r = http.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-haiku-4-5-20251001", "max_tokens": 10,
                      "messages": [{"role": "user", "content": [
                          {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                          {"type": "text", "text": PHASE2_PROMPT}]}]},
                timeout=30)
            verdict = "YES"  # default KEEP
            raw_answer = ""
            if r.status_code == 200:
                raw_answer = r.json()["content"][0]["text"].strip()
                # Only delete if response is literally "NO" — anything else = KEEP
                verdict = "NO" if raw_answer.upper().strip().rstrip(".") == "NO" else "YES"
        except Exception:
            verdict = "YES"
            raw_answer = "ERROR"

        if test_count:
            # Test mode: print raw response, never delete
            label = "✗ DELETE" if verdict == "NO" else "✓ KEEP"
            print(f"  [P2] [{i+1}/{len(with_img)}] {label}: {title}")
            print(f"         Haiku raw: \"{raw_answer}\" → {verdict}")
            return

        if verdict == "NO":
            if dry_run:
                print(f"  [P2] [{i+1}/{len(with_img)}] ✗ WOULD DELETE: {title}")
            else:
                if delete_product(pid, token):
                    with _file_lock: deleted[0] += 1
                    prog["phase2_deleted"].append({"id": pid, "title": title, "image": img_url})
                    print(f"  [P2] [{i+1}/{len(with_img)}] ✗ DELETE: {title}")
                time.sleep(0.3)
        else:
            with _file_lock: kept[0] += 1
            if (i+1) % 100 == 0:
                rate = (i+1) / max(time.time()-t0, 1) * 60
                print(f"  [P2] [{i+1}/{len(with_img)}] kept={kept[0]} deleted={deleted[0]} | {rate:.0f}/min")

        if not test_count:
            prog["phase2_done"].append(pid)
            save_progress(prog)

    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(classify_one, (i, p)) for i, p in enumerate(with_img)]
        for f in as_completed(futs):
            try: f.result()
            except Exception as e: print(f"  [P2] error: {e}")

    if deleted[0] >= 50:
        print(f"  ⚠ SAFETY: 50 deletions reached. Review deleted products in cleanup_progress.json.")
        print(f"  Reset phase2_done in cleanup_progress.json to re-scan, or continue with --phase 2")
    print(f"  Phase 2 done: {kept[0]} kept, {deleted[0]} deleted")
    return deleted[0]

# ── Phase 3: Re-categorise ──
def phase3(products, token, prog, dry_run):
    print(f"\n  ══ Phase 3: Re-categorise products ══")
    collection_map = json.loads(COLLECTION_MAP_FILE.read_text()) if COLLECTION_MAP_FILE.exists() else {}
    done_set = set(prog["phase3_done"])
    todo = [p for p in products if p["id"] not in done_set]
    print(f"  {len(todo)} products to check\n")
    moved, unchanged = 0, 0
    headers = _headers(token)

    for i, p in enumerate(todo):
        if _shutdown.is_set(): break
        pid, title = p["id"], p.get("title", "")
        tags = [t.strip() for t in (p.get("tags", "") or "").split(",") if t.strip()]
        current_cat = next((t for t in tags if t in collection_map), None)
        new_cat, _, new_parent = categorize(title)

        if new_cat and new_cat != current_cat:
            moved += 1
            if dry_run:
                print(f"  [P3] [{i+1}/{len(todo)}] MOVE: {current_cat} → {new_cat} | {title[:55]}")
            else:
                new_tags = [t for t in tags if t not in collection_map]
                if new_cat: new_tags.append(new_cat)
                if new_parent: new_tags.append(new_parent)
                try:
                    http.put(f"{_base()}/products/{pid}.json", headers=headers,
                        json={"product": {"id": pid, "tags": ", ".join(new_tags)}}, timeout=15)
                except Exception: pass
                for h in [new_cat, new_parent]:
                    if h and h in collection_map:
                        try:
                            http.post(f"{_base()}/collects.json", headers=headers,
                                json={"collect": {"product_id": pid, "collection_id": collection_map[h]}}, timeout=15)
                        except Exception: pass
                        time.sleep(0.3)
                prog["phase3_moved"].append({"id": pid, "from": current_cat, "to": new_cat, "title": title[:60]})
                print(f"  [P3] [{i+1}/{len(todo)}] MOVED: {current_cat} → {new_cat} | {title[:55]}")
        else:
            unchanged += 1

        prog["phase3_done"].append(pid)
        if (i+1) % 100 == 0:
            save_progress(prog)
            print(f"  [P3] [{i+1}/{len(todo)}] moved={moved} unchanged={unchanged}")
        time.sleep(0.3)
    save_progress(prog)
    print(f"  Phase 3 done: {moved} moved, {unchanged} unchanged")
    return moved

# ── Phase 4: Pull reviews ──
def phase4(products, token, prog, dry_run):
    print(f"\n  ══ Phase 4: Pull AliExpress reviews ══")
    if not ALI_STATE_FILE.exists():
        print("  No ali_state.json — skipping Phase 4")
        return 0

    api_key = config.ANTHROPIC_API_KEY
    done_set = set(prog["phase4_done"])

    # Build ali_id → shopify_pid mapping
    pushed = json.loads(PUSHED_TITLES_FILE.read_text()) if PUSHED_TITLES_FILE.exists() else {}
    cp = json.loads(CHECKPOINT_FILE.read_text()) if CHECKPOINT_FILE.exists() else {"products": []}
    ali_map = {}
    for p in cp.get("products", []):
        m = re.search(r"/item/(\d+)\.html", p.get("product_url", ""))
        if not m: continue
        ali_id = m.group(1)
        for spid, data in pushed.items():
            if data.get("raw_title") == p.get("product_title"):
                if int(spid) not in done_set:
                    ali_map[ali_id] = int(spid)
                break

    print(f"  {len(ali_map)} products need reviews (~{len(ali_map)*10//60} min)")
    if not ali_map:
        print("  Nothing to process.")
        return 0

    from playwright.sync_api import sync_playwright
    ENGLISH_NAMES = ["James", "Sarah", "Michael", "Emma", "David", "Sophie", "Daniel",
                     "Olivia", "Thomas", "Lucy", "Chris", "Hannah", "Ben", "Katie"]

    reviewed = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, channel="msedge",
            args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(viewport={"width":1366,"height":768}, locale="en-GB",
            storage_state=str(ALI_STATE_FILE))
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        ctx.route("**/*.{png,jpg,jpeg,gif,svg,webp,woff,woff2,mp4,webm}", lambda r: r.abort())
        page = ctx.new_page()

        for idx, (ali_id, spid) in enumerate(ali_map.items()):
            if _shutdown.is_set(): break
            print(f"  [P4] [{idx+1}/{len(ali_map)}] fetching {ali_id}...", end=" ", flush=True)

            try:
                page.goto(f"https://www.aliexpress.com/item/{ali_id}.html", wait_until="commit", timeout=20000)
                time.sleep(1)
                if "punish" in page.url.lower() or "x5sec" in page.url.lower():
                    print("captcha, waiting 60s")
                    time.sleep(60); continue

                raw = page.evaluate(f"""async () => {{
                    try {{
                        const r = await fetch('https://feedback.aliexpress.com/pc/searchEvaluation.do?productId={ali_id}&page=1&pageSize=20&sort=complex_default', {{credentials:'include'}});
                        return await r.text();
                    }} catch(e) {{ return ''; }}
                }}""")

                reviews = []
                if raw and len(raw) > 50:
                    data = json.loads(raw)
                    for item in (data.get("data") or {}).get("evaViewList", []):
                        rating = item.get("buyerEval", 50)
                        rating = rating // 10 if rating > 5 else rating
                        if rating < 4: continue
                        text = (item.get("buyerFeedback") or "").strip()
                        if not text or len(text) < 10: continue
                        name = item.get("buyerName", "")
                        if not name or "aliexpress" in name.lower() or sum(1 for c in name if ord(c)<128)/max(len(name),1) < 0.5:
                            name = f"{random.choice(ENGLISH_NAMES)} {chr(random.randint(65,90))}."
                        else:
                            parts = name.split()
                            name = f"{parts[0]} {parts[-1][0]}." if len(parts) >= 2 else name[:8]+"."
                        reviews.append({"name": name, "rating": rating, "text": text[:500],
                            "date": (item.get("evalDate") or "")[:10], "images": []})

                reviews.sort(key=lambda r: -r["rating"])
                reviews = reviews[:12]
                print(f"{len(reviews)} reviews")

                if reviews and not dry_run:
                    avg = round(sum(r["rating"] for r in reviews) / len(reviews), 1)
                    dist = {str(i): sum(1 for r in reviews if r["rating"]==i) for i in range(1,6)}
                    headers = _headers(token)
                    for mf in [
                        {"namespace": "reviews", "key": "aliexpress", "value": json.dumps(reviews), "type": "json"},
                        {"namespace": "reviews", "key": "average", "value": str(avg), "type": "single_line_text_field"},
                        {"namespace": "reviews", "key": "count", "value": str(len(reviews)), "type": "single_line_text_field"},
                        {"namespace": "reviews", "key": "distribution", "value": json.dumps(dist), "type": "json"},
                    ]:
                        try: http.post(f"{_base()}/products/{spid}/metafields.json", headers=headers, json={"metafield": mf}, timeout=15)
                        except: pass
                        time.sleep(0.3)
                    reviewed += 1

                prog["phase4_done"].append(spid)
                if (idx+1) % 25 == 0: save_progress(prog)
            except Exception as e:
                print(f"error: {str(e)[:60]}")

            time.sleep(random.uniform(1.0, 2.0))

        page.close(); ctx.close(); browser.close()
    save_progress(prog)
    print(f"  Phase 4 done: {reviewed} products with reviews")
    return reviewed

# ── Main ──
def main():
    dry_run = "--dry-run" in sys.argv
    phase_filter = None
    test_count = 0
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--phase" and i+1 < len(args):
            phase_filter = int(args[i+1]); i += 2; continue
        if args[i] == "--test" and i+1 < len(args):
            test_count = int(args[i+1]); i += 2; continue
        i += 1
    if "--reset-phase2" in sys.argv:
        prog = load_progress()
        prog["phase2_done"] = []
        prog["phase2_deleted"] = []
        save_progress(prog)
        print("  Reset Phase 2 progress.")

    print(f"  DEBUG argv: {sys.argv}")
    print(f"  DEBUG parsed: phase={phase_filter} test={test_count} dry_run={dry_run}")

    token = get_shopify_token()
    prog = load_progress()

    print(f"\n══════════════════════════════════════")
    print(f"  CastForge Full Cleanup Pipeline")
    print(f"══════════════════════════════════════")
    print(f"  Dry run: {dry_run}")
    if test_count:
        print(f"  TEST MODE: classify {test_count} products only (no deletions)")
    if phase_filter:
        print(f"  Running phase {phase_filter} only")
    print()

    print("  Fetching all products...")
    products = fetch_all_products(token)
    print(f"  Total: {len(products)} products\n")

    p1_del, p2_del, p3_moved, p4_rev = 0, 0, 0, 0

    if not phase_filter or phase_filter == 1:
        if not test_count:
            p1_del = phase1(products, token, prog, dry_run)
            if p1_del > 0 and not dry_run:
                products = [p for p in products if p["id"] not in set(prog["phase1_done"])]

    if not phase_filter or phase_filter == 2:
        if not _shutdown.is_set():
            p2_del = phase2(products, token, prog, dry_run, test_count=test_count)
            if p2_del > 0 and not dry_run:
                del_ids = set(d["id"] for d in prog["phase2_deleted"])
                products = [p for p in products if p["id"] not in del_ids]

    if not phase_filter or phase_filter == 3:
        if not _shutdown.is_set():
            p3_moved = phase3(products, token, prog, dry_run)

    if not phase_filter or phase_filter == 4:
        if not _shutdown.is_set():
            p4_rev = phase4(products, token, prog, dry_run)

    print(f"\n══════════════════════════════════════")
    print(f"  FINAL SUMMARY")
    print(f"══════════════════════════════════════")
    print(f"  Phase 1: {p1_del} deleted (0 images)")
    print(f"  Phase 2: {p2_del} deleted (bad images)")
    print(f"  Phase 3: {p3_moved} re-categorised")
    print(f"  Phase 4: {p4_rev} reviews pushed")
    print()

if __name__ == "__main__":
    main()
