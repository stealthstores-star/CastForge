#!/usr/bin/env python3
"""
Create an interactive Scale Guide page on Shopify.

Features:
- Dropdown to select scale (1/6 to 1/700)
- Shows actual mm height of a 6ft human at that scale
- SVG soldier silhouette resized to scale next to a reference coin
- Fully JS-driven, no backend needed

Usage: python3 create_scale_guide.py
"""
import json
import requests
import config
from uploader import get_shopify_token

SCALES_DATA = [
    {"label": "1/6 (300mm)", "ratio": 6, "mm": 305, "common": "Action figures, high-end display"},
    {"label": "1/8 (228mm)", "ratio": 8, "mm": 228, "common": "Large busts, anime garage kits"},
    {"label": "1/9 (203mm)", "ratio": 9, "mm": 203, "common": "Busts, portrait figures"},
    {"label": "1/10 (183mm)", "ratio": 10, "mm": 183, "common": "Busts, display figures"},
    {"label": "1/12 (152mm)", "ratio": 12, "mm": 152, "common": "Large display figures"},
    {"label": "1/16 (114mm)", "ratio": 16, "mm": 114, "common": "Large military figures"},
    {"label": "1/18 (100mm)", "ratio": 18, "mm": 100, "common": "Vehicle crew figures"},
    {"label": "1/20 (90mm)", "ratio": 20, "mm": 90, "common": "Display figures, competition pieces"},
    {"label": "1/24 (75mm)", "ratio": 24, "mm": 75, "common": "Display figures, car models"},
    {"label": "1/32 (56mm)", "ratio": 32, "mm": 56, "common": "Large wargaming, Heroic scale"},
    {"label": "1/35 (52mm)", "ratio": 35, "mm": 52, "common": "Military models, dioramas"},
    {"label": "1/48 (38mm)", "ratio": 48, "mm": 38, "common": "Aircraft, some military"},
    {"label": "1/56 (32mm)", "ratio": 56, "mm": 32, "common": "Warhammer, Bolt Action"},
    {"label": "1/64 (28mm)", "ratio": 64, "mm": 28, "common": "Tabletop wargaming standard"},
    {"label": "1/72 (25mm)", "ratio": 72, "mm": 25, "common": "Aircraft, small military"},
    {"label": "1/87 (21mm)", "ratio": 87, "mm": 21, "common": "HO scale trains"},
    {"label": "1/100 (18mm)", "ratio": 100, "mm": 18, "common": "Flames of War, small wargaming"},
    {"label": "1/144 (13mm)", "ratio": 144, "mm": 13, "common": "Aircraft, Gundam"},
    {"label": "1/200 (9mm)", "ratio": 200, "mm": 9, "common": "Small aircraft, ships"},
    {"label": "1/350 (5mm)", "ratio": 350, "mm": 5, "common": "Ship models"},
    {"label": "1/700 (3mm)", "ratio": 700, "mm": 3, "common": "Waterline ship models"},
]

PAGE_HTML = """
<div class="cf-scale-guide" id="cf-scale-guide">
  <div class="cf-sg-intro">
    <p>Not sure which scale is right for you? Use this interactive guide to see exactly how tall a standard 6ft (183cm) human figure would be at each scale, compared to an everyday coin.</p>
  </div>

  <div class="cf-sg-controls">
    <label for="cf-sg-select" class="cf-sg-label">Select a scale</label>
    <select id="cf-sg-select" class="cf-sg-select"></select>
  </div>

  <div class="cf-sg-display">
    <div class="cf-sg-visual" id="cf-sg-visual">
      <svg id="cf-sg-svg" viewBox="0 0 300 350" width="300" height="350">
        <!-- Reference coin (UK pound, ~23mm diameter, shown at fixed size) -->
        <circle id="cf-sg-coin" cx="80" cy="320" r="20" fill="#c9a84c" opacity="0.9"/>
        <text x="80" y="325" text-anchor="middle" font-size="8" fill="#000" font-weight="bold">£1</text>
        <text x="80" y="340" text-anchor="middle" font-size="7" fill="#888">23mm</text>

        <!-- Soldier silhouette (scaled dynamically) -->
        <g id="cf-sg-soldier" transform="translate(180, 310)">
          <!-- Simple soldier silhouette path, origin at feet -->
          <path d="M0,0 L-6,-12 L-8,-25 L-12,-40 L-10,-55 L-8,-65 L-12,-70 L-10,-80 L-6,-85 L-4,-90 L-3,-92 L0,-95 L3,-92 L4,-90 L6,-85 L10,-80 L12,-70 L8,-65 L10,-55 L12,-40 L8,-25 L6,-12 Z" fill="#FF6B1A" opacity="0.9"/>
          <!-- Rifle -->
          <path d="M12,-70 L16,-75 L18,-95 L16,-95 L14,-76 L10,-72" fill="#FF6B1A" opacity="0.7"/>
          <!-- Head circle -->
          <circle cx="0" cy="-100" r="6" fill="#FF6B1A" opacity="0.9"/>
          <!-- Helmet -->
          <ellipse cx="0" cy="-103" rx="7" ry="4" fill="#FF6B1A" opacity="0.7"/>
        </g>

        <!-- Height label -->
        <text id="cf-sg-height-label" x="180" y="15" text-anchor="middle" font-size="14" fill="#FF6B1A" font-weight="bold"></text>
        <text id="cf-sg-height-mm" x="180" y="30" text-anchor="middle" font-size="10" fill="#888"></text>

        <!-- Height line -->
        <line id="cf-sg-line" x1="220" y1="310" x2="220" y2="310" stroke="#FF6B1A" stroke-width="1" stroke-dasharray="3,3" opacity="0.5"/>
      </svg>
    </div>

    <div class="cf-sg-info" id="cf-sg-info">
      <div class="cf-sg-stat">
        <span class="cf-sg-stat__label">Scale</span>
        <span class="cf-sg-stat__value" id="cf-sg-ratio"></span>
      </div>
      <div class="cf-sg-stat">
        <span class="cf-sg-stat__label">Figure height</span>
        <span class="cf-sg-stat__value" id="cf-sg-mm"></span>
      </div>
      <div class="cf-sg-stat">
        <span class="cf-sg-stat__label">Common uses</span>
        <span class="cf-sg-stat__value cf-sg-stat__value--small" id="cf-sg-common"></span>
      </div>
      <a href="/collections/all" class="cf-sg-cta">Browse Models in This Scale →</a>
    </div>
  </div>

  <div class="cf-sg-table">
    <h3>Quick Reference</h3>
    <table>
      <thead><tr><th>Scale</th><th>Height (mm)</th><th>Common Uses</th></tr></thead>
      <tbody id="cf-sg-tbody"></tbody>
    </table>
  </div>
</div>

<style>
.cf-scale-guide{max-width:800px;margin:0 auto;padding:20px;font-family:'Inter',-apple-system,sans-serif;color:#e8e8e8;}
.cf-sg-intro{font-size:15px;line-height:1.7;color:#888;margin-bottom:32px;}
.cf-sg-controls{margin-bottom:32px;}
.cf-sg-label{display:block;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:8px;}
.cf-sg-select{width:100%;max-width:400px;padding:12px 16px;background:#141414;border:1px solid #222;border-radius:8px;color:#e8e8e8;font-size:16px;cursor:pointer;}
.cf-sg-select:focus{border-color:#FF6B1A;outline:none;}
.cf-sg-display{display:grid;grid-template-columns:300px 1fr;gap:32px;align-items:start;margin-bottom:48px;}
.cf-sg-visual{background:#141414;border:1px solid #222;border-radius:12px;padding:16px;text-align:center;}
.cf-sg-info{display:flex;flex-direction:column;gap:16px;}
.cf-sg-stat{background:#141414;border:1px solid #222;border-radius:8px;padding:16px;}
.cf-sg-stat__label{display:block;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:4px;}
.cf-sg-stat__value{font-family:'Bebas Neue',Impact,sans-serif;font-size:28px;color:#FF6B1A;}
.cf-sg-stat__value--small{font-family:'Inter',sans-serif;font-size:14px;color:#e8e8e8;}
.cf-sg-cta{display:block;text-align:center;padding:14px;background:#FF6B1A;color:#fff;font-weight:700;font-size:14px;text-transform:uppercase;letter-spacing:1px;text-decoration:none;border-radius:8px;}
.cf-sg-cta:hover{background:#FF8844;}
.cf-sg-table{margin-top:32px;}
.cf-sg-table h3{font-family:'Bebas Neue',Impact,sans-serif;font-size:20px;color:#FF6B1A;text-transform:uppercase;letter-spacing:1px;margin:0 0 16px;}
.cf-sg-table table{width:100%;border-collapse:collapse;}
.cf-sg-table th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#888;padding:8px 12px;border-bottom:2px solid #222;}
.cf-sg-table td{font-size:13px;color:#e8e8e8;padding:10px 12px;border-bottom:1px solid #1a1a1a;}
.cf-sg-table tr:hover td{background:#141414;}
@media(max-width:768px){.cf-sg-display{grid-template-columns:1fr;}}
</style>

<script>
(function(){
  var scales = SCALES_DATA_PLACEHOLDER;

  var select = document.getElementById('cf-sg-select');
  var soldier = document.getElementById('cf-sg-soldier');
  var heightLabel = document.getElementById('cf-sg-height-label');
  var heightMm = document.getElementById('cf-sg-height-mm');
  var ratioEl = document.getElementById('cf-sg-ratio');
  var mmEl = document.getElementById('cf-sg-mm');
  var commonEl = document.getElementById('cf-sg-common');
  var lineEl = document.getElementById('cf-sg-line');
  var ctaEl = document.querySelector('.cf-sg-cta');
  var tbody = document.getElementById('cf-sg-tbody');

  // Populate select
  scales.forEach(function(s, i) {
    var opt = document.createElement('option');
    opt.value = i;
    opt.textContent = s.label;
    if (s.ratio === 35) opt.selected = true;
    select.appendChild(opt);
  });

  // Populate reference table
  scales.forEach(function(s) {
    var tr = document.createElement('tr');
    tr.innerHTML = '<td>1/' + s.ratio + '</td><td>' + s.mm + 'mm</td><td>' + s.common + '</td>';
    tbody.appendChild(tr);
  });

  function update() {
    var s = scales[select.value];
    var mm = s.mm;

    // Map mm to SVG pixels. Coin is 23mm = 40px diameter (20px radius).
    // So 1mm = 40/23 ≈ 1.74 px
    var pxPerMm = 40 / 23;
    var soldierPx = Math.min(mm * pxPerMm, 290);

    // Scale the soldier group. Original soldier is ~106px tall (from feet at 0 to helmet top at -106)
    var scaleFactor = soldierPx / 106;
    soldier.setAttribute('transform', 'translate(180, 310) scale(' + scaleFactor + ')');

    // Height label
    heightLabel.textContent = '1/' + s.ratio;
    heightMm.textContent = mm + 'mm tall';

    // Position label above soldier
    var topY = 310 - soldierPx;
    heightLabel.setAttribute('y', Math.max(topY - 10, 14));
    heightMm.setAttribute('y', Math.max(topY + 4, 28));

    // Height line
    lineEl.setAttribute('y1', '310');
    lineEl.setAttribute('y2', String(topY));

    // Info panel
    ratioEl.textContent = '1/' + s.ratio;
    mmEl.textContent = mm + 'mm';
    commonEl.textContent = s.common;

    // CTA link
    if (s.ratio <= 10) ctaEl.href = '/collections/busts-portraits';
    else if (s.ratio <= 56) ctaEl.href = '/collections/all?q=1/' + s.ratio;
    else ctaEl.href = '/collections/all';
  }

  select.addEventListener('change', update);
  update();
})();
</script>
""".replace("SCALES_DATA_PLACEHOLDER", json.dumps(SCALES_DATA))


def main():
    token = get_shopify_token()
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    base = f"https://{config.SHOPIFY_STORE}/admin/api/{config.API_VERSION}"

    print("\n  Creating interactive Scale Guide page\n")

    # Check if page already exists
    r = requests.get(f"{base}/pages.json?handle=scale-guide", headers=headers, timeout=15)
    pages = r.json().get("pages", []) if r.status_code == 200 else []
    existing = [p for p in pages if p.get("handle") == "scale-guide"]

    if existing:
        # Update existing page
        pid = existing[0]["id"]
        r = requests.put(f"{base}/pages/{pid}.json", headers=headers, json={
            "page": {"id": pid, "body_html": PAGE_HTML, "title": "Scale Guide — Find Your Perfect Size"}
        }, timeout=15)
        if r.status_code == 200:
            print(f"  Updated existing page (ID: {pid})")
        else:
            print(f"  Update failed: {r.status_code}")
    else:
        # Create new page
        r = requests.post(f"{base}/pages.json", headers=headers, json={
            "page": {
                "title": "Scale Guide — Find Your Perfect Size",
                "handle": "scale-guide",
                "body_html": PAGE_HTML,
                "published": True
            }
        }, timeout=15)
        if r.status_code == 201:
            print(f"  Created page: /pages/scale-guide")
        else:
            print(f"  Create failed: {r.status_code} {r.text[:200]}")

    print("  Done!\n")


if __name__ == "__main__":
    main()
