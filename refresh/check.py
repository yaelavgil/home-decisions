#!/usr/bin/env python3
"""Refresh pass over the board: python3 refresh/check.py [--cat slug,slug|all] [--max-age DAYS] [--workers N] [--limit N]

Reads the items from the built index.html (so it sees exactly what the board shows), checks every URL, and writes
refresh/status.json (merged: only the checked items are replaced).  build.py overlays status.json on the board.
"""
import json, sys, os, argparse, datetime, concurrent.futures as cf, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib

REPO = lib.REPO
STATUS = os.path.join(REPO, "refresh", "status.json")


def load_board():
    s = open(os.path.join(REPO, "index.html"), encoding="utf-8").read()

    def grab(tag):
        i = s.index(tag) + len(tag)
        return json.JSONDecoder().raw_decode(s[i:])[0]
    items = grab("const BITEMS=")
    cats = grab("BCATS=")
    return items, cats


def now():
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds")


def refs_of(it):
    """[(key, url, listed_price)] — every distinct URL that backs this item."""
    out, seen = [], set()

    def add(k, u, p):
        if u and u not in seen:
            seen.add(u); out.append((k, u, p))
    for i, st in enumerate(it.get("stores") or []):
        add("store:%d" % i, st.get("l"), st.get("p0", st.get("p")))
    add("link", it.get("link"), it.get("price0", it.get("price")))
    for i, pt in enumerate(it.get("parts") or []):
        add("part:%d" % i, pt.get("l"), pt.get("p"))
    return out


def judge(it, results):
    """Turn raw per-URL results into item-level flags + the recommended live price."""
    flags = []
    rec = None
    sts = it.get("stores") or []
    rec_i = next((i for i, s in enumerate(sts) if s.get("rec")), 0 if sts else None)
    for r in results:
        listed = r.get("listed")
        live = r.get("priceNis")
        r["delta"] = None
        if r.get("conf") == "low":
            flags.append(("unsure", r["k"], "קראתי מחיר ₪%d אבל לא בוודאות — לבדוק ידנית" % round(live or 0)))
            r["priceNis"] = live = None
        if live is not None and listed:
            r["delta"] = round((live - listed) / listed, 3)
        is_rec = r["k"] == ("store:%d" % rec_i if rec_i is not None else "link") or (rec_i is None and r["k"] == "link")
        r["rec"] = is_rec
        if is_rec:
            rec = r
    for r in results:
        tag = "המלצה" if r.get("rec") else "חנות"
        st = r["status"]
        if st == "dead":
            flags.append(("dead", r["k"], "הקישור לא קיים יותר (404)"))
        elif st == "moved":
            flags.append(("moved", r["k"], "הקישור מפנה לעמוד כללי — המוצר כנראה הוסר"))
        elif st == "blocked":
            flags.append(("blocked", r["k"], "האתר חוסם בדיקה אוטומטית — נדרש דפדפן"))
        elif st == "error":
            flags.append(("error", r["k"], "שגיאת רשת: " + str(r.get("note") or "")))
        elif st == "noprice":
            flags.append(("noprice", r["k"], "לא הצלחתי לקרוא מחיר מהעמוד"))
        if st == "ok" and r.get("avail") == "out":
            flags.append(("oos", r["k"], "אזל מהמלאי"))
        d = r.get("delta")
        if d is not None and abs(d) > 0.35:
            flags.append(("price_big", r["k"], "פער גדול: באתר ₪%d לעומת ₪%d בלוח — לבדוק (וריאנט / סט / מחיר אחר)" % (round(r["priceNis"]), round(r["listed"]))))
        elif d is not None and abs(d) > 0.03:
            flags.append(("price_up" if d > 0 else "price_down", r["k"], "המחיר באתר ₪%d לעומת ₪%d בלוח (%+d%%)" % (round(r["priceNis"]), round(r["listed"]), round(d * 100))))
        if r.get("was") and r.get("priceNis"):
            flags.append(("sale", r["k"], "מבצע: ₪%d במקום ₪%d" % (round(r["priceNis"]), round(r["was"] * lib.FX.get((r.get("cur") or "ILS").upper(), 1.0)))))
        im = r.get("img") or {}
        if im.get("local") and im["local"] != "ok":
            flags.append(("img_bad", r["k"], "תמונה לא תקינה בלוח (%s)" % im["local"]))
        if im.get("match") == "different":
            flags.append(("img_diff", r["k"], "התמונה בעמוד האתר נראית שונה מהתמונה בלוח"))
    return flags, rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cat", default="all")
    ap.add_argument("--max-age", type=float, default=0, help="skip items checked less than N days ago")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="")
    a = ap.parse_args()

    items, cats = load_board()
    slug_of = {c["key"]: c.get("slug") for c in cats}
    want = None if a.cat == "all" else set(a.cat.split(","))
    ids = set(a.ids.split(",")) if a.ids else None
    status = json.load(open(STATUS, encoding="utf-8")) if os.path.exists(STATUS) else {"items": {}}
    todo = []
    for it in items:
        if it.get("hidden") or it.get("type") == "color":
            continue
        if want is not None and slug_of.get(it.get("cat")) not in want:
            continue
        if ids and it["id"] not in ids:
            continue
        prev = status["items"].get(it["id"])
        if a.max_age and prev:
            t = datetime.datetime.fromisoformat(prev["t"])
            if (datetime.datetime.now(t.tzinfo) - t).total_seconds() < a.max_age * 86400:
                continue
        if refs_of(it):
            todo.append(it)
    if a.limit:
        todo = todo[:a.limit]
    jobs = []
    for it in todo:
        imgs = it.get("imgs") or ([it["img"]] if it.get("img") else [])
        for j, (k, u, p) in enumerate(refs_of(it)):
            jobs.append((it, k, u, p, imgs if j == 0 else None))
    print("items", len(todo), "urls", len(jobs), flush=True)

    def run(job):
        it, k, u, p, imgs = job
        try:
            r = lib.check_url(u, p, imgs)
        except Exception as e:  # noqa
            r = {"url": u, "status": "error", "note": "%s: %s" % (type(e).__name__, str(e)[:100])}
        r["k"] = k; r["listed"] = p
        return it["id"], r

    by = collections.defaultdict(list)
    done = 0
    with cf.ThreadPoolExecutor(a.workers) as ex:
        for iid, r in ex.map(run, jobs):
            by[iid].append(r)
            done += 1
            if done % 40 == 0:
                print("  ", done, "/", len(jobs), flush=True)
    t = now()
    byid = {it["id"]: it for it in todo}
    for iid, results in by.items():
        it = byid[iid]
        flags, rec = judge(it, results)
        prevrec = (status["items"].get(iid) or {})
        entry = {"t": t, "name": (it.get("name") or "")[:70], "cat": it.get("cat"),
                 "flags": [{"f": f, "k": k, "msg": m} for f, k, m in flags],
                 "refs": [{x: r.get(x) for x in ("k", "url", "status", "http", "price", "cur", "priceNis", "listed", "delta", "avail", "was", "how", "rec", "img", "note", "final", "variantsPrices","via","conf") if r.get(x) is not None} for r in results]}
        lp = (rec or {}).get("priceNis")
        if lp is not None:
            entry["live"] = lp
            if (rec or {}).get("was"):
                entry["was"] = rec["was"]
        old = prevrec.get("live")
        if old is not None and lp is not None and abs(old - lp) > 0.5:
            entry["prev"] = {"price": old, "t": prevrec["t"]}
        elif prevrec.get("prev") and lp is not None:
            entry["prev"] = prevrec["prev"]
        status["items"][iid] = entry
    status["generated"] = t
    json.dump(status, open(STATUS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # summary
    c = collections.Counter(f["f"] for e in (status["items"][i] for i in by) for f in e["flags"])
    sc = collections.Counter(r["status"] for rs in by.values() for r in rs)
    print("url status:", dict(sc))
    print("flags:", dict(c))


if __name__ == "__main__":
    main()
