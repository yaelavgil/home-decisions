# Refresh — מחירים, קישורים, תמונות וחנויות

The board's data goes stale (prices change, products sell out, links die). This folder is the refresh machinery.

## Layers
1. **Deterministic check** — `python3 refresh/check.py --cat <slug,slug|all> [--max-age DAYS] [--ids A1,B2]`
   For every URL of every visible product (`link`, `stores[].l`, `parts[].l`): fetches the page (plain HTTP first; **real headless Chrome** when
   a site is Cloudflare/JS-walled), classifies it (`ok / dead / moved / blocked / noprice / error`), reads live price + stock + sale
   (JSON-LD → Shopify `.js` → meta → markup (low confidence, never auto-applied)), and compares our local image with the page's main image.
   Writes `refresh/status.json` (only the checked items are replaced; `prev` keeps the previous live price).
   `build.py` overlays it: store price ← live price when it's an ILS page, parsed with high confidence and within ±35% of the source price
   (the source price stays in `p0` / `price0`; bigger jumps are flagged, not applied). Cards show "✓ נבדק לפני N ימים", ▲▼ "עודכן מ־₪X", 🏷 sale, 🔴 dead link, ⚠️ out of stock, 🖼 image check, ❔ not verified.
   Foreign-currency pages (USD…) are never auto-applied.
   politeness: ≥1.2s between requests per host, 6.5s for bpatent.
2. **Agent pass (judgement)** — for what the script can't decide (`blocked`, `noprice`, `unsure`, `img_diff`, big jumps, dead links) and, for
   the "רענון + חלופות" mode / items checked >30 days ago: re-verify in a real browser, fix the source (build.py / category json / enrich),
   and do a mini search for better results on the same or similar items in other stores (follow memory `home-product-search-workflow`; never buy/contact).
3. **Button on the board** — category strip: "🔄 מחירים וחנויות … [רענון] [רענון + חלופות]" writes `/requests/<id>` with `reason:"refresh"`, `mode:"check"|"deep"`
   (same Firebase channel as research requests, see RESEARCH-REQUESTS.md). `python3 refresh/refresh_requests.py` lists them; `… run` executes the deterministic part.

Order of a refresh: `check.py` → `build.py` → commit (message in English) + push → mark requests done.
