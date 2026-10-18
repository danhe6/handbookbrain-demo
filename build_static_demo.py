"""Build a read-only, static copy of the web UI (no server, no LLM, no API key) for hosting on GitHub Pages.
    python -m hb --company gitlab-gtm serve          # in another terminal, graph loaded
    python scripts/build_static_demo.py              # -> ../handbookbrain-demo/
"""
import argparse, hashlib, json, re, shutil, sys, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
SAFE = "-_.!~*'()"


def enc(s):
    return quote(str(s), safe=SAFE)


def norm(url):
    u = urlsplit(url)
    q = sorted(parse_qsl(u.query, keep_blank_values=True))
    return unquote(u.path) + ("?" + "&".join(f"{k}={v}" for k, v in q) if q else "")


class Crawler:
    def __init__(self, base, out, timeout):
        self.base, self.out, self.timeout = base.rstrip("/"), out, timeout
        self.index, self.data, self.failed = {}, {}, []

    def get(self, url):
        key = norm(url)
        if key in self.data:
            return self.data[key]
        try:
            with urllib.request.urlopen(self.base + url, timeout=self.timeout) as r:
                d = json.loads(r.read())
        except urllib.error.HTTPError as e:
            self.failed.append((url, f"HTTP {e.code}")); self.data[key] = None; return None
        except Exception as e:  # noqa: BLE001
            self.failed.append((url, repr(e)[:120])); self.data[key] = None; return None
        self.data[key] = d
        return d

    def many(self, urls, workers=1):
        urls = [u for u in dict.fromkeys(urls) if norm(u) not in self.data]
        if not urls:
            return
        print(f"  fetching {len(urls)} …", flush=True)
        with ThreadPoolExecutor(workers) as ex:
            list(ex.map(self.get, urls))

    def save(self, key, d):
        name = hashlib.sha1(key.encode()).hexdigest()[:20] + ".json"
        (self.out / "static" / "snap" / name).write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
        self.index[key] = name


def collect(obj, keys, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, str) and v:
                out.add(v)
            collect(v, keys, out)
    elif isinstance(obj, list):
        for v in obj:
            collect(v, keys, out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default=str(ROOT.parent / "handbookbrain-demo"))
    ap.add_argument("--max-pages", type=int, default=400)
    ap.add_argument("--max-terms", type=int, default=300)
    ap.add_argument("--timeout", type=int, default=120)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        for p in out.iterdir():
            if p.name != ".git":
                shutil.rmtree(p) if p.is_dir() else p.unlink()
    (out / "static" / "snap").mkdir(parents=True, exist_ok=True)
    c = Crawler(a.base, out, a.timeout)

    print("1/6 core views")
    ov = c.get("/api/overview")
    if not ov:
        sys.exit(f"API not reachable at {a.base} — start `python -m hb --company gitlab-gtm serve` first. {c.failed}")
    c.many(["/api/companies", "/api/trust", "/api/graph/schema", "/api/graph/explore", "/api/updates?limit=200",
            "/api/answers?limit=40", "/api/review", "/api/proposals", "/api/decisions/triage", "/api/learn/areas",
            "/api/glossary", "/api/sync", "/api/cypher/run?i=0"])
    print("2/6 answer stories")
    ids = {x["id"] for x in (c.data.get(norm("/api/answers?limit=40")) or {}).get("answers", [])}
    for x in (c.data.get(norm("/api/review")) or {}).get("stale_answers", []):
        ids.add(x.get("id"))
    c.many(["/api/story/" + enc(i) for i in ids if i])
    print("3/6 learn areas")
    areas = [x["id"] for x in (c.data.get(norm("/api/learn/areas")) or {}).get("areas", [])]
    c.many([u for ar in areas for u in ("/api/learn/area?a=" + enc(ar), "/api/learn/brief?a=" + enc(ar),
                                         "/api/glossary?area=" + enc(ar))], workers=1)
    print("4/6 change impact")
    shas = set(); collect(list(c.data.values()), {"sha"}, shas)
    c.many(["/api/impact/" + enc(s) for s in shas])
    print("5/6 documents")
    seen = set()
    for _ in range(2):
        paths = set(); collect(list(c.data.values()), {"path"}, paths)
        paths = sorted(p for p in paths if p not in seen and not p.startswith(("http", "/api")))[: max(0, a.max_pages - len(seen))]
        seen |= set(paths)
        c.many([u for p in paths for u in ("/api/page?path=" + enc(p), "/api/graph/page?path=" + enc(p))])
    print("6/6 glossary terms")
    names = set()
    for k, v in c.data.items():
        if k.startswith("/api/glossary") and v:
            names |= {t["name"] for t in v.get("terms", []) if t.get("name")}
    c.many(["/api/term?name=" + enc(n) for n in sorted(names)[: a.max_terms]], workers=1)

    cs = c.data.get(norm("/api/companies"))
    if cs:
        cs["companies"] = [x for x in cs["companies"] if x["id"] == cs["current"]]
    ov["sync"] = {"running": False, "log": [], "error": None}
    ans = c.data.get(norm("/api/answers?limit=40"))
    if ans:
        ans["suggested"] = []
    n = 0
    for k, v in c.data.items():
        if v is not None:
            c.save(k, v); n += 1
    (out / "static" / "snap" / "index.json").write_text(json.dumps(c.index, ensure_ascii=False))
    for f in (ROOT / "web").rglob("*"):
        if f.is_file() and f.name != "index.html":
            dst = out / "static" / f.relative_to(ROOT / "web")
            dst.parent.mkdir(parents=True, exist_ok=True)
            if f.suffix in (".js", ".css"):
                dst.write_text(f.read_text().replace("'/static/", "'static/").replace("`/static/", "`static/").replace('"/static/', '"static/'))
            else:
                shutil.copy2(f, dst)
    shutil.copy2(Path(__file__).with_name("demo_shim.js"), out / "static" / "demo.js")
    html = (ROOT / "web" / "index.html").read_text().replace('"/static/', '"static/')
    html = re.sub(r'(<script src="static/graph\.js)', r'<script src="static/demo.js"></script>\n\1', html, count=1)
    (out / "index.html").write_text(html)
    (out / ".nojekyll").write_text("")
    (out / "README.md").write_text(
        f"# HandbookBrain — read-only demo\n\nStatic snapshot of the HandbookBrain UI ({ov.get('name')}, docs as of "
        f"{str(ov.get('as_of'))[:10]}). Every view is the real API output saved as JSON; asking new questions, sync "
        "and approvals need the full local setup: https://github.com/danhe6/handbookbrain#quickstart\n")
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file() and ".git" not in p.parts) / 1e6
    print(f"\nsaved {n} responses, {size:.1f} MB -> {out}")
    if c.failed:
        print(f"{len(c.failed)} requests failed:")
        for u, e in c.failed[:15]:
            print("  ", e, u)


if __name__ == "__main__":
    main()
