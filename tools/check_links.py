#!/usr/bin/env python3
"""
check_links.py -- link checker for benoitcollins.github.io

Scans every .html file in the repository and reports:
  * internal links whose target file or #anchor does not exist
  * external links (http/https) that do not answer, if --external is given

Usage, from anywhere:
    python3 tools/check_links.py              # internal links only (fast, offline)
    python3 tools/check_links.py --external   # also test every external URL

The site root is deduced from this script's location (its parent directory),
so there is no path to edit.

Notes on false positives when using --external:
  * Some sites (zbMATH, Centrair, university directories) answer 403 to any
    non-browser request. They are flagged but are usually fine in a browser.
  * A "redirect" is not an error: the link works, but the target has moved and
    it may be worth updating the URL.
"""

import argparse
import html
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LINK_RE = re.compile(r'(?:href|src)\s*=\s*["\']([^"\']+)["\']', re.I)
ANCHOR_RE = re.compile(r'(?:id|name)\s*=\s*["\']([^"\']+)["\']', re.I)
SKIP_SCHEMES = ("mailto:", "javascript:", "data:", "tel:")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")


def html_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in (".git", "tools")]
        for f in filenames:
            if f.lower().endswith((".html", ".htm")):
                out.append(os.path.join(dirpath, f))
    return sorted(out)


def collect():
    """Return (list of broken internal links, {external url: [locations]})."""
    files = html_files()
    anchors = {}
    for f in files:
        txt = open(f, encoding="utf-8", errors="replace").read()
        anchors[os.path.relpath(f, ROOT)] = set(ANCHOR_RE.findall(txt))

    broken, external, n_internal = [], {}, 0
    for f in files:
        rel = os.path.relpath(f, ROOT)
        txt = open(f, encoding="utf-8", errors="replace").read()
        for m in LINK_RE.finditer(txt):
            raw = m.group(1).strip()
            line = txt[:m.start()].count("\n") + 1
            if raw.startswith(SKIP_SCHEMES):
                continue
            if raw.startswith(("http://", "https://", "//")):
                url = "https:" + raw if raw.startswith("//") else raw
                # href values are HTML-escaped in the source; a browser decodes
                # them before requesting, so decode here too.
                external.setdefault(html.unescape(url), []).append(f"{rel}:{line}")
                continue
            if raw.startswith("#"):
                n_internal += 1
                frag = urllib.parse.unquote(raw[1:])
                if frag and frag not in anchors[rel]:
                    broken.append((rel, line, raw, "anchor not found in this page"))
                continue
            path, _, frag = raw.partition("#")
            path = urllib.parse.unquote(path)
            if not path:
                continue
            n_internal += 1
            target = os.path.normpath(os.path.join(os.path.dirname(f), path))
            if os.path.isdir(target):
                if not os.path.exists(os.path.join(target, "index.html")):
                    broken.append((rel, line, raw, "directory without index.html"))
                continue
            if not os.path.exists(target):
                broken.append((rel, line, raw, "file not found"))
                continue
            trel = os.path.relpath(target, ROOT)
            frag = urllib.parse.unquote(frag)
            if frag and trel in anchors and frag not in anchors[trel]:
                broken.append((rel, line, raw, f"anchor #{frag} not found in {trel}"))
    return files, n_internal, broken, external


def probe(url):
    """Return (url, status_or_None, final_url, error). Fetches no page content."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
                return url, r.status, r.geturl(), ""
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code in (400, 403, 405, 501):
                continue          # some servers dislike HEAD; retry with GET
            return url, e.code, "", str(e.reason)
        except Exception as e:
            if method == "HEAD":
                continue
            return url, None, "", f"{type(e).__name__}: {e}"
    return url, None, "", "unreachable"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--external", action="store_true",
                    help="also check external URLs over the network (slower)")
    ap.add_argument("--json", metavar="FILE",
                    help="write the external-URL results to FILE as JSON")
    args = ap.parse_args()

    files, n_internal, broken, external = collect()
    print(f"site root: {ROOT}")
    print(f"HTML files scanned: {len(files)}")
    print(f"internal links checked: {n_internal}")
    print(f"distinct external URLs: {len(external)}")

    print("\n=== BROKEN INTERNAL LINKS ===")
    if not broken:
        print("none")
    for rel, line, raw, why in broken:
        print(f"{rel}:{line}  {raw}\n    -> {why}")

    if not args.external:
        print("\n(run with --external to test the external URLs too)")
        return 1 if broken else 0

    with ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(probe, list(external)))

    bad, redirected, ok = [], [], []
    for url, status, final, err in results:
        if status is None or status >= 400:
            bad.append((url, status, err))
            continue
        a = url.rstrip("/")
        b = (final or "").rstrip("/")
        (redirected if b and b != a else ok).append((url, status, final))

    print(f"\n=== EXTERNAL: {len(ok)} ok, {len(redirected)} redirected, {len(bad)} problems ===")
    print("\n--- PROBLEMS ---")
    if not bad:
        print("none")
    for url, status, err in sorted(bad, key=lambda x: str(x[1])):
        print(f"[{status}] {url}\n    {err}\n    on: {', '.join(external[url])}")

    print("\n--- REDIRECTS (link works, target moved) ---")
    if not redirected:
        print("none")
    for url, status, final in redirected:
        print(f"{url}\n    -> {final}\n    on: {', '.join(external[url])}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({u: {"status": s, "final": f, "error": e,
                           "locations": external[u]}
                       for u, s, f, e in results}, fh, indent=1)
        print(f"\nJSON written to {args.json}")

    return 1 if (broken or bad) else 0


if __name__ == "__main__":
    sys.exit(main())
