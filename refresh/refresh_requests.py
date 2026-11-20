#!/usr/bin/env python3
"""Board refresh requests (button "רענון" / "רענון + חלופות" on a category) live in Firebase /requests with reason:"refresh".

  python3 refresh/refresh_requests.py            # list pending refresh requests
  python3 refresh/refresh_requests.py run        # run the deterministic check for each pending one, mark done (does NOT build/commit)
Mode "deep" = also needs an agent pass for alternatives (see refresh/README.md); this script only marks it "running".
"""
import json, sys, os, subprocess, urllib.request
DB = "https://home-picks-47450-default-rtdb.europe-west1.firebasedatabase.app"
HERE = os.path.dirname(os.path.abspath(__file__))


def get(path):
    return json.load(urllib.request.urlopen(DB + path, timeout=30))


def patch(path, obj):
    rq = urllib.request.Request(DB + path, data=json.dumps(obj).encode(), method="PATCH", headers={"Content-Type": "application/json"})
    urllib.request.urlopen(rq, timeout=30).read()


def pending():
    r = get("/requests.json") or {}
    return [(k, v) for k, v in r.items() if isinstance(v, dict) and v.get("reason") == "refresh" and v.get("status") in ("pending", "running")]


if __name__ == "__main__":
    cats = json.load(open(os.path.join(HERE, "..", "cats.json"))) if os.path.exists(os.path.join(HERE, "..", "cats.json")) else None
    P = pending()
    if not P:
        print("no pending refresh requests"); sys.exit(0)
    for k, v in P:
        print(k, v.get("status"), v.get("mode"), v.get("cat"), v.get("label"))
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        sys.path.insert(0, HERE)
        import check
        items, bc = check.load_board()
        slug = {c["key"]: c.get("slug") for c in bc}
        for k, v in P:
            s = slug.get(v.get("cat"))
            if not s:
                continue
            patch("/requests/%s.json" % k, {"status": "running"})
            subprocess.run([sys.executable, os.path.join(HERE, "check.py"), "--cat", s], check=False)
            if v.get("mode") != "deep":
                patch("/requests/%s.json" % k, {"status": "done", "summary": "הבדיקה הסתיימה — מחירים וקישורים עודכנו"})
