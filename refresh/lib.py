"""Deterministic price/link/image checker for the home-decisions board.

No LLM involved. For every product URL the board knows (item.link, item.stores[].l, item.parts[].l) it:
  * fetches the page (Chrome UA, he-IL), classifies: ok / dead (404/410) / moved (redirect to a non-product page) /
    blocked (bot wall -> needs a real browser) / error
  * extracts the live price + availability + sale info from JSON-LD, meta tags, Shopify .js, WooCommerce/Magento markup
  * compares to the price the board shows and fetches the page's main image to compare with our local image
Results are plain JSON (see check.py); build.py overlays them on the board.
"""
import json, re, time, threading, hashlib, io, os, html as _html
from urllib.parse import urlparse, urljoin, unquote
import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
HDR = {"User-Agent": UA, "Accept-Language": "he-IL,he;q=0.9,en;q=0.8",
       "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

# USD->ILS used only to compare foreign-currency pages with the ILS price shown on the board (same ~3.34 she uses)
FX = {"ILS": 1.0, "NIS": 1.0, "USD": 3.34, "EUR": 3.9, "GBP": 4.5}

# domains that never answer plain HTTP (JS wall / bot protection) -> marked "blocked" quickly, handled by the browser pass
JS_ONLY = ("ksp.co.il", "aliexpress.com", "amazon.com", "amazon.co.uk", "temu.com", "etsy.com")
# per-domain politeness (seconds between requests); bpatent bans at < 6s
DELAY = {"bpatent.co.il": 6.5, "www.bpatent.co.il": 6.5}
DEFAULT_DELAY = 1.2

_lock = threading.Lock()
_last = {}


def _wait(host):
    d = DELAY.get(host, DEFAULT_DELAY)
    with _lock:
        now = time.time()
        t = max(now, _last.get(host, 0) + d)
        _last[host] = t
    if t > now:
        time.sleep(t - now)


def host_of(u):
    return (urlparse(u).netloc or "").lower()


def fetch(url, timeout=25, binary=False, tries=2):
    host = host_of(url)
    last = None
    for i in range(tries):
        _wait(host)
        try:
            r = requests.get(url, headers=HDR, timeout=timeout, allow_redirects=True)
            return r
        except Exception as e:  # noqa
            last = e
            time.sleep(1.5)
    raise last


# ----------------------------------------------------------------------------- price extraction
def _num(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    s = re.sub(r"[^\d.,]", "", s)
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", "") if re.search(r",\d{3}(\D|$)", s) else s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _jsonld(html):
    out = []
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            out.append(json.loads(m.group(1).strip()))
        except Exception:
            try:
                out.append(json.loads(re.sub(r",\s*([}\]])", r"\1", m.group(1).strip())))
            except Exception:
                pass
    return out


def _walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def _avail(a):
    a = str(a or "")
    if "OutOfStock" in a or "SoldOut" in a or "Discontinued" in a:
        return "out"
    if "InStock" in a or "LimitedAvailability" in a or "OnlineOnly" in a:
        return "in"
    if "PreOrder" in a or "BackOrder" in a:
        return "pre"
    return None


def parse_page(html, url):
    """-> dict(price, cur, avail, sale_from, name, image, how)"""
    res = {"price": None, "cur": None, "avail": None, "was": None, "name": None, "image": None, "how": None}
    # 1) JSON-LD Product/Offer
    for blk in _jsonld(html):
        for o in _walk(blk):
            t = o.get("@type")
            t = t if isinstance(t, list) else [t]
            if "Product" in t or "ProductGroup" in t:
                res["name"] = res["name"] or o.get("name")
                im = o.get("image")
                if isinstance(im, list):
                    im = im[0] if im else None
                if isinstance(im, dict):
                    im = im.get("url")
                res["image"] = res["image"] or im
                offs = o.get("offers")
                offs = offs if isinstance(offs, list) else ([offs] if offs else [])
                prices = []
                for of in offs:
                    if not isinstance(of, dict):
                        continue
                    p = _num(of.get("price") or of.get("lowPrice"))
                    if p is None:
                        ps = of.get("priceSpecification")
                        ps = ps if isinstance(ps, list) else ([ps] if ps else [])
                        for x in ps:
                            if isinstance(x, dict) and _num(x.get("price")) is not None:
                                p = _num(x.get("price")); break
                    if p:
                        cur = of.get("priceCurrency")
                        if not cur and isinstance(of.get("priceSpecification"), dict):
                            cur = of["priceSpecification"].get("priceCurrency")
                        prices.append((p, cur, _avail(of.get("availability"))))
                if prices:
                    lo = min(prices, key=lambda x: x[0])
                    res["price"], res["cur"], res["avail"] = lo[0], (lo[1] or "ILS"), lo[2]
                    res["how"] = "jsonld"
                    break
        if res["how"]:
            break
    # 2) OpenGraph / product meta
    if res["price"] is None:
        m = re.search(r'<meta[^>]+(?:property|name)=["\'](?:product:price:amount|og:price:amount|twitter:data1)["\'][^>]+content=["\']([^"\']+)', html, re.I) \
            or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:product:price:amount|og:price:amount)["\']', html, re.I)
        if m and _num(m.group(1)):
            res["price"] = _num(m.group(1)); res["how"] = "meta"
            c = re.search(r'(?:product:price:currency|og:price:currency)["\'][^>]+content=["\']([A-Z]{3})', html, re.I)
            res["cur"] = c.group(1).upper() if c else "ILS"
    # 3) itemprop price
    if res["price"] is None:
        m = re.search(r'itemprop=["\']price["\'][^>]*content=["\']([\d.,]+)', html, re.I) or \
            re.search(r'content=["\']([\d.,]+)["\'][^>]*itemprop=["\']price["\']', html, re.I)
        if m and _num(m.group(1)):
            res["price"] = _num(m.group(1)); res["how"] = "itemprop"; res["cur"] = "ILS"
    # 4) WooCommerce / Magento visible price block (ILS)
    if res["price"] is None:
        m = re.search(r'class="[^"]*(?:woocommerce-Price-amount|price-final_price|special-price|product-price)[^"]*"[^>]*>(?:.*?)(?:₪|&#8362;|&#x20aa;)?\s*([\d,]+(?:\.\d+)?)', html, re.S | re.I)
        if m and _num(m.group(1)):
            res["price"] = _num(m.group(1)); res["how"] = "markup"; res["cur"] = "ILS"
    # sale detection: <del>/<s>/old-price with a number larger than the live price
    if res["price"]:
        olds = []
        for pat in (r"<del[^>]*>(.*?)</del>", r'class="[^"]*(?:old-price|compare-at|price--compare|was-price|regular-price)[^"]*"[^>]*>(.*?)</', ):
            for m in re.finditer(pat, html[:400000], re.S | re.I):
                v = _num(re.sub(r"<[^>]+>", " ", m.group(1)))
                if v and v > res["price"] * 1.04 and v < res["price"] * 5:
                    olds.append(v)
        if olds:
            res["was"] = olds[0]
    if not res["image"]:
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html, re.I)
        if m:
            res["image"] = m.group(1)
    if res["avail"] is None:
        # WooCommerce marks the main product's post class: instock / outofstock / onbackorder (first occurrence = main product)
        m = re.search(r'class="[^"]*\b(instock|outofstock|onbackorder)\b', html)
        if m:
            res["avail"] = {"instock": "in", "outofstock": "out", "onbackorder": "pre"}[m.group(1)]
        elif not re.search(r"הוסף\s*לסל|הוספה\s*לסל|הוסיפו\s*לסל|add[\s-]*to[\s-]*cart|הוסף\s*לעגלה|הוספה\s*לעגלה", html, re.I) \
                and re.search(r"אזל\s*מהמלאי|אזל\s*במלאי|לא\s*במלאי|המוצר\s*אזל", re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S), re.I):
            res["avail"] = "out"
    if res["image"]:
        res["image"] = urljoin(url, _html.unescape(res["image"]))
    return res


def shopify_js(url):
    """Shopify /products/<handle>.js is authoritative (price, compare_at_price, available)."""
    m = re.search(r"^(https?://[^/]+)/(?:[a-z]{2}(?:-[a-z]{2})?/)?products/([^/?#]+)", url, re.I)
    if not m:
        return None
    try:
        r = fetch(m.group(1) + "/products/" + m.group(2) + ".js", timeout=20, tries=1)
        if r.status_code != 200 or not r.text.lstrip().startswith("{"):
            return None
        j = r.json()
    except Exception:
        return None
    vs = j.get("variants") or []
    avs = [v for v in vs if v.get("available")]
    pool = avs or vs
    if not pool:
        return None
    best = min(pool, key=lambda v: v.get("price") or 1e12)
    div = 100.0
    out = {"price": (best.get("price") or 0) / div, "cur": "ILS", "how": "shopify", "name": j.get("title"),
           "avail": "in" if avs else "out", "image": ("https:" + j["featured_image"]) if str(j.get("featured_image") or "").startswith("//") else j.get("featured_image"),
           "was": None}
    ca = best.get("compare_at_price")
    if ca and ca > best.get("price", 0):
        out["was"] = ca / div
    if len(vs) > 1:
        ps = sorted({(v.get("price") or 0) / div for v in vs})
        out["variantsPrices"] = ps
    return out


# ----------------------------------------------------------------------------- image helpers
def _ahash(img):
    from PIL import Image
    import numpy as np
    g = img.convert("L").resize((16, 16), Image.LANCZOS)
    a = np.asarray(g, dtype=float)
    return (a > a.mean()).flatten()


def _dist(h1, h2):
    return int((h1 != h2).sum())


def load_local_img(path):
    from PIL import Image
    p = os.path.join(REPO, path)
    if not os.path.exists(p):
        return None, "missing"
    try:
        im = Image.open(p); im.load()
        if im.width < 60 or im.height < 60:
            return None, "tiny"
        return im, "ok"
    except Exception:
        return None, "corrupt"


def check_image(item_imgs, page_img_url):
    """Return {'local': 'ok|missing|corrupt', 'match': 'same|different|unknown'}"""
    from PIL import Image
    out = {"local": None, "match": "unknown"}
    hs = []
    st = []
    for p in item_imgs[:4]:
        if p.startswith("http"):
            try:
                r = requests.get(p, headers=HDR, timeout=20)
                im = Image.open(io.BytesIO(r.content)); im.load()
                st.append("ok"); hs.append(_ahash(im))
            except Exception:
                st.append("broken")
            continue
        im, s = load_local_img(p)
        st.append(s)
        if im is not None:
            hs.append(_ahash(im))
    out["local"] = "ok" if st and all(x == "ok" for x in st) else (",".join(sorted(set(st))) if st else "none")
    if page_img_url and hs:
        try:
            _wait(host_of(page_img_url))
            r = requests.get(page_img_url, headers=HDR, timeout=20)
            im = Image.open(io.BytesIO(r.content)); im.load()
            ph = _ahash(im)
            d = min(_dist(ph, h) for h in hs)
            out["match"] = "same" if d <= 56 else "different"   # 256-bit hash; sites crop/recolor, so be lenient
            out["dist"] = d
        except Exception:
            out["match"] = "unknown"
    return out


# ----------------------------------------------------------------------------- headless Chrome fallback
import subprocess, tempfile, shutil, threading as _th
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
_chrome_sem = _th.Semaphore(3)


def fetch_chrome(url, budget=9000, hard=75):
    """Real Chrome (real TLS fingerprint + JS) dumps the rendered DOM. Returns html or ''."""
    if not os.path.exists(CHROME):
        return ""
    with _chrome_sem:
        _wait(host_of(url))
        prof = tempfile.mkdtemp(prefix="chk-")

        def run(ms):
            p = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--user-data-dir=" + prof,
                                "--virtual-time-budget=%d" % ms, "--dump-dom", url],
                               capture_output=True, timeout=hard)
            return p.stdout.decode("utf-8", "replace")
        try:
            html = run(budget)
            # The JS+cookie interstitial sets its cookie and reloads itself. Under --dump-dom that reload
            # often doesn't land inside the virtual-time budget, so we get the stub. Loading a second time
            # in the SAME profile sends the cookie it just set and returns the real page.
            if len(html) < 6000 and re.search(r"needs? JavaScript and cookies|לאפשר\s+JavaScript"
                                              r"|<title>[^<]*(?:טוען|Loading)", html[:4000], re.I):
                _wait(host_of(url))
                html = run(max(budget, 15000)) or html
            return html
        except Exception:
            return ""
        finally:
            shutil.rmtree(prof, ignore_errors=True)


# ----------------------------------------------------------------------------- one URL
def classify_redirect(orig, final):
    a, b = urlparse(orig), urlparse(final)
    pa = unquote(a.path).strip("/"); pb = unquote(b.path).strip("/")
    if not pb and pa:
        return True
    if pa and pb and len(pb) < 6 and len(pa) > 14:
        return True
    if "/" + pb != "/" + pa and re.search(r"(?:^|/)(?:category|collections?|shop|search|404|error)(?:/|$)", pb, re.I) \
            and not re.search(r"(?:^|/)(?:product|products|p|item)(?:/|$)", pb, re.I):
        return True
    return False


def check_url(url, listed_price=None, imgs=None):
    host = host_of(url)
    out = {"url": url, "status": None, "price": None, "cur": None, "avail": None, "was": None, "how": None, "http": None}
    if not url.startswith("http"):
        out["status"] = "nolink"; return out
    html = None
    final = url
    if not any(host.endswith(d) for d in JS_ONLY):
        try:
            r = fetch(url)
        except Exception as e:  # noqa
            out["status"] = "error"; out["note"] = str(e)[:120]; return out
        out["http"] = r.status_code
        final = r.url
        if r.status_code in (404, 410):
            out["status"] = "dead"; return out
        walled = r.status_code in (401, 403, 429, 503) or (r.status_code == 200 and (
            re.search(r"cf-challenge|Just a moment|Access Denied|px-captcha", r.text[:4000], re.I)
            # JS+cookie interstitial served with 200 OK (electricshop / vero-cafe …): a stub page that
            # sets a cookie and reloads. Without this it parses as "no price" instead of "blocked",
            # so the browser pass never runs and the card lies with ❔ "מחיר לא נקרא".
            or (len(r.text) < 6000 and re.search(
                r"needs? JavaScript and cookies|enable JavaScript and cookies"
                r"|לאפשר\s+JavaScript|<title>[^<]*(?:טוען\s*\.{0,3}|Loading)\s*(?:/|\.|<)", r.text[:4000], re.I))))
        if not walled and r.status_code >= 400:
            out["status"] = "error"; out["note"] = "HTTP %d" % r.status_code; return out
        if not walled:
            html = r.text
    if html is None:       # blocked / JS-only -> real headless Chrome
        html = fetch_chrome(url)
        out["via"] = "chrome"
        if len(html) < 8000 or re.search(r"<title>[^<]*(?:Just a moment|Access Denied|Attention Required)", html, re.I) or re.search(r"404|לא נמצא|Page not found", re.sub(r"<script.*?</script>", "", html[:20000], flags=re.S)[:6000]) and len(html) < 60000:
            out["status"] = "blocked"; out["note"] = "גם דפדפן אמיתי לא נכנס — לבדיקה ידנית"; return out
    if final != url and classify_redirect(url, final):
        out["status"] = "moved"; out["final"] = final; return out
    info = (None if out.get("via") == "chrome" else shopify_js(final)) or parse_page(html, final)
    if info.get("how") != "shopify":
        p2 = parse_page(html, final)
        info = p2
    out.update({k: info.get(k) for k in ("price", "cur", "avail", "was", "how", "name", "image", "variantsPrices")})
    out["status"] = "ok"
    if out.get("how") == "markup":
        out["conf"] = "low"
    if out["price"] is not None and out["price"] < 5:      # "1" / "0" placeholders are parse artefacts, not prices
        out["price"] = None
    if out["price"] is not None:
        out["priceNis"] = round(out["price"] * FX.get((out["cur"] or "ILS").upper(), 1.0), 2)
    else:
        out["status"] = "noprice"
    if imgs is not None:
        out["img"] = check_image(imgs, info.get("image"))
    return out
