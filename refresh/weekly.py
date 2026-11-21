#!/usr/bin/env python3
"""Weekly refresh — runs the deterministic pass over the whole board and writes a human report.

    python3 refresh/weekly.py [--max-age 5] [--workers 10]

What it does (read-only on the outside world: only GETs product pages, never logs in, never contacts anyone):
  1. snapshots refresh/status.json
  2. runs check.py for every category (items checked < --max-age days ago are skipped)
  3. diffs the new status against the snapshot -> refresh/weekly-report.md + refresh/weekly-report.json
  4. python3 build.py  (rebuilds index.html locally)
It does NOT commit or push. Publishing happens only after Yael approves:  python3 refresh/weekly.py --publish
"""
import json, os, sys, subprocess, argparse, datetime, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
STATUS = os.path.join(HERE, "status.json")
REPORT_MD = os.path.join(HERE, "weekly-report.md")
REPORT_JSON = os.path.join(HERE, "weekly-report.json")
PY = sys.executable


def load(p):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"items": {}}


def flagset(e):
    return {(f["f"], f.get("k")) for f in (e or {}).get("flags", [])}


def diff(old, new):
    price, newflags, gone = [], [], []
    for iid, e in new["items"].items():
        o = old["items"].get(iid)
        if not o or o.get("t") == e.get("t"):
            continue  # not re-checked this run
        lo, ln = o.get("live"), e.get("live")
        if lo is not None and ln is not None and abs(ln - lo) / max(lo, 1) >= 0.03:
            price.append({"id": iid, "name": e.get("name"), "cat": e.get("cat"), "from": lo, "to": ln})
        nf = flagset(e) - flagset(o)
        bad = [f for f in nf if f[0] in ("dead", "moved", "oos", "price_big", "sale", "blocked")]
        if bad:
            msgs = [m["msg"] for m in e["flags"] if (m["f"], m.get("k")) in bad]
            newflags.append({"id": iid, "name": e.get("name"), "cat": e.get("cat"),
                             "flags": sorted({b[0] for b in bad}), "msgs": msgs})
        back = [f for f in flagset(o) - flagset(e) if f[0] in ("dead", "moved", "oos")]
        if back:
            gone.append({"id": iid, "name": e.get("name"), "cat": e.get("cat"), "flags": sorted({b[0] for b in back})})
    return price, newflags, gone


def write_report(price, newflags, gone, checked, t0):
    lines = ["# רענון שבועי — %s" % t0.strftime("%d.%m.%Y"), "",
             "נבדקו %d פריטים. מחירים שזזו ≥3%%: %d · בעיות חדשות: %d · בעיות שנפתרו: %d" % (checked, len(price), len(newflags), len(gone)), ""]
    if price:
        lines += ["## מחירים ששונו", ""]
        for x in sorted(price, key=lambda x: x["to"] - x["from"]):
            lines.append("- %s (%s): ₪%d → ₪%d (%+d%%)" % (x["name"], x["cat"], round(x["from"]), round(x["to"]), round((x["to"] - x["from"]) / x["from"] * 100)))
        lines.append("")
    if newflags:
        lines += ["## בעיות חדשות", ""]
        for x in newflags:
            lines.append("- %s (%s): %s" % (x["name"], x["cat"], " · ".join(x["msgs"][:2])))
        lines.append("")
    if gone:
        lines += ["## נפתרו", ""]
        for x in gone:
            lines.append("- %s (%s): %s" % (x["name"], x["cat"], ", ".join(x["flags"])))
    open(REPORT_MD, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    json.dump({"date": t0.isoformat(timespec="seconds"), "checked": checked, "price": price, "newflags": newflags, "gone": gone},
              open(REPORT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def publish():
    run = lambda *a: subprocess.run(a, cwd=REPO, check=True)
    run(PY, "build.py")
    run("git", "add", "refresh/status.json", "index.html", "c", "picks/index.html", "s/index.html", "compare/index.html")
    msg = "Board: weekly price/link refresh %s\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" % datetime.date.today().isoformat()
    run("git", "commit", "-m", msg)
    run("git", "push")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age", default="5")
    ap.add_argument("--workers", default="10")
    ap.add_argument("--publish", action="store_true", help="after approval: rebuild, commit and push the refreshed board")
    a = ap.parse_args()
    if a.publish:
        return publish()
    t0 = datetime.datetime.now().astimezone()
    old = json.loads(json.dumps(load(STATUS)))
    r = subprocess.run([PY, os.path.join(HERE, "check.py"), "--cat", "all", "--max-age", a.max_age, "--workers", a.workers], cwd=REPO)
    if r.returncode:
        sys.exit("check.py failed")
    new = load(STATUS)
    price, newflags, gone = diff(old, new)
    checked = sum(1 for i, e in new["items"].items() if old["items"].get(i, {}).get("t") != e.get("t"))
    write_report(price, newflags, gone, checked, t0)
    subprocess.run([PY, "build.py"], cwd=REPO, check=True)
    print(open(REPORT_MD, encoding="utf-8").read())


if __name__ == "__main__":
    main()
