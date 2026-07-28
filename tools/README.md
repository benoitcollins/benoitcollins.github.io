# tools

Maintenance scripts for this website. Nothing here is part of the published
site content; the files are visible publicly (the repository is public), but
they contain no credentials or private data.

## check_links.py

Checks every `.html` file in the repository for broken links.

```sh
python3 tools/check_links.py              # internal links only — fast, no network
python3 tools/check_links.py --external   # also test every external URL
```

Requires Python 3 only (no packages to install). Exit status is 0 when
everything is fine, 1 when something is broken, so it can be used in a
pre-push check.

What it reports:

- **Broken internal links** — an `href`/`src` pointing to a file that is not in
  the repository, or to an `#anchor` that does not exist in the target page.
- **Problems** (with `--external`) — external URLs that return an error status
  or do not answer at all.
- **Redirects** (with `--external`) — the link still works, but the target has
  moved; worth updating the URL at some point.

### Interpreting the external results

Some servers refuse requests that do not come from a real browser and answer
`403 Forbidden` even though the page is perfectly fine — zbMATH, Centrair and
several university directory pages behave this way. Always open a flagged URL
in a browser before deleting it.

Last full run: 2026-07-28 — 66 internal links, 131 external URLs, no genuine
breakage.
