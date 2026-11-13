#!/usr/bin/env python3
"""Checks the product pages listed in stockwatch.json and writes the result to the shared
catalog in Firebase (picks/_catalog/items/<id>: oos, oosChecked). The board shows an
"אזל מהמלאי" banner on every item whose oos flag is true and removes it when it is back in stock."""
import json, os, re, sys, time, urllib.request, urllib.error
DB = "https://home-picks-47450-default-rtdb.europe-west1.firebasedatabase.app"
HERE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "he,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "ignore")

def status(html):
    """True = out of stock, False = in stock, None = could not tell."""
    av = [a.lower() for a in re.findall(r'"availability"\s*:\s*"([^"]+)"', html.replace("\\/", "/"))]
    if av:
        a = av[0]  # the Product of the page comes first in the JSON-LD
        if any(k in a for k in ("outofstock", "soldout", "discontinued")): return True
        if any(k in a for k in ("instock", "limitedavailability", "onlineonly", "preorder")): return False
    if re.search(r'class="[^"]*\bstock\b[^"]*out-of-stock[^"]*"', html) or re.search(r'class="[^"]*out-of-stock[^"]*\bstock\b', html): return True
    if re.search(r'<p class="stock in-stock', html): return False
    m = re.search(r'"available"\s*:\s*(true|false)', html)
    if m: return m.group(1) == "false"
    return None

def put(id, body):
    req = urllib.request.Request(f"{DB}/picks/_catalog/items/{id}.json", data=json.dumps({"id": id, **body}).encode(), method="PATCH", headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=30).read()

def main():
    watch = json.load(open(os.path.join(HERE, "..", "stockwatch.json"), encoding="utf-8"))
    bad = 0
    for id, w in watch.items():
        try:
            oos = status(fetch(w["url"]))
        except Exception as e:
            print(id, "fetch failed:", e); bad += 1; continue
        if oos is None:
            print(id, "status unclear — left as is"); bad += 1; continue
        put(id, {"oos": oos, "oosChecked": int(time.time() * 1000)})
        print(id, w.get("name", ""), "OUT OF STOCK" if oos else "in stock")
    return 1 if bad == len(watch) else 0

if __name__ == "__main__":
    sys.exit(main())
