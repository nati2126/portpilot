"""Build the QNX Port Atlas candidate list: popular C/C++ CMake projects not yet ported to QNX.

    python atlas/candidates.py --ported build-files-ports.txt --out atlas/candidates.json

Uses the public GitHub search API without a token (10 searches/minute, so it paces itself)
and raw.githubusercontent.com to check for a top-level CMakeLists.txt. `--ported` is a file
with one existing port name per line (from github.com/qnx-ports/build-files/ports).
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = {"User-Agent": "portpilot-atlas", "Accept": "application/vnd.github+json"}

# Keywords that mark libraries in markets QNX serves (topics or description).
MARKETS = {
    "industrial": ["opc-ua", "opcua", "modbus", "industrial", "plc", "fieldbus", "ethercat"],
    "automotive": ["can", "canbus", "autosar", "vehicle", "automotive", "obd", "someip"],
    "robotics": ["robotics", "ros", "ros2", "slam", "kinematics", "motion-planning", "mavlink"],
    "messaging": ["mqtt", "dds", "zeromq", "messaging", "pubsub", "rpc", "protobuf", "coap"],
    "medical": ["medical", "dicom", "hl7", "healthcare"],
    "data": ["json", "serialization", "compression", "parser", "yaml", "xml", "msgpack"],
    "security": ["crypto", "tls", "ssl", "cryptography", "security"],
}
SKIP_TOPICS = {"game", "gui", "qt", "android", "ios", "windows", "kernel", "linux-kernel",
               "cuda", "gpu", "emulator", "game-engine", "editor", "browser", "neovim"}


def get(url: str, timeout: float = 30) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed hosts)
        return bytes(r.read())


def search(lang: str, min_stars: int, pages: int, cache: Path) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for page in range(1, pages + 1):
        cf = cache / f"{lang.replace('+', 'p')}-{min_stars}-{page}.json"
        if cf.exists():
            items = json.loads(cf.read_text(encoding="utf-8"))
            out += items
            if len(items) < 100:
                break
            continue
        # '+' in a query string means a space: C++ must be sent as C%2B%2B
        q = (f"language:{urllib.parse.quote(lang, safe='')}+stars:>={min_stars}"
             "+archived:false+fork:false")
        url = (f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc"
               f"&per_page=100&page={page}")
        for attempt in range(8):
            try:
                items = json.loads(get(url)).get("items", [])
                break
            except urllib.error.HTTPError as e:
                if e.code in (403, 429) and attempt < 7:
                    # wait until the reset time GitHub reports (or Retry-After)
                    reset = e.headers.get("x-ratelimit-reset")
                    wait = float(e.headers.get("retry-after") or 0) or (
                        max(5.0, float(reset) - time.time() + 3) if reset else 65.0)
                    print(f"  rate limited; waiting {wait:.0f}s", file=sys.stderr, flush=True)
                    time.sleep(min(wait, 900))
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, http.client.HTTPException):
                if attempt < 4:
                    time.sleep(10 * (attempt + 1))
                    continue
                raise
        cache.mkdir(parents=True, exist_ok=True)
        cf.write_text(json.dumps(items), encoding="utf-8")
        out += items
        print(f"  {lang} page {page}: {len(items)}", file=sys.stderr, flush=True)
        if len(items) < 100:
            break
        time.sleep(10)  # stay well under 10 searches/minute
    return out


def has_cmake(full: str, branch: str) -> bool | None:
    """True/False from raw.githubusercontent.com; None if it could not be checked."""
    for attempt in range(3):
        try:
            get(f"https://raw.githubusercontent.com/{full}/{branch}/CMakeLists.txt", timeout=15)
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
        except (urllib.error.URLError, TimeoutError, http.client.HTTPException):
            pass
        time.sleep(3 * (attempt + 1))
    return None


def markets(repo: dict[str, object]) -> list[str]:
    topics = {str(t).lower() for t in repo.get("topics") or []}  # type: ignore[union-attr]
    desc = str(repo.get("description") or "").lower()
    words = set(desc.replace(",", " ").replace(".", " ").split())
    return [m for m, keys in MARKETS.items()
            if any(k in topics or k in words for k in keys)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ported", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-stars", type=int, default=800)
    ap.add_argument("--pages", type=int, default=10)
    ap.add_argument("--cache", type=Path, default=Path.home() / ".cache" / "portpilot" / "gh")
    a = ap.parse_args()
    ported = {ln.strip().lower() for ln in a.ported.read_text().splitlines() if ln.strip()}
    repos: dict[str, dict[str, object]] = {}
    for lang in ("C", "C++"):
        for r in search(lang, a.min_stars, a.pages, a.cache):
            repos.setdefault(str(r["full_name"]), r)
    rows = []
    for i, (full, r) in enumerate(sorted(repos.items(), key=lambda kv: -int(kv[1]["stargazers_count"]))):  # type: ignore[call-overload]  # noqa: E501
        name = str(r["name"]).lower()
        topics = {str(t).lower() for t in r.get("topics") or []}  # type: ignore[union-attr]
        row = {"repo": full, "url": r["html_url"], "stars": r["stargazers_count"],
               "language": r["language"], "branch": r["default_branch"],
               "size_kb": r.get("size", 0), "pushed_at": r.get("pushed_at", ""),
               "description": (r.get("description") or "")[:200],
               "topics": sorted(topics), "markets": markets(r),
               "already_ported": name in ported}
        if row["already_ported"] or topics & SKIP_TOPICS:
            row["cmake"] = None
        else:
            row["cmake"] = has_cmake(full, str(r["default_branch"]))
        rows.append(row)
        if i % 50 == 0:
            print(f"  checked {i}/{len(repos)}", file=sys.stderr, flush=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    cands = [r for r in rows if r["cmake"]]
    print(f"{len(rows)} repos, {sum(1 for r in rows if r['already_ported'])} already ported, "
          f"{len(cands)} CMake candidates, "
          f"{sum(1 for r in cands if r['markets'])} in QNX markets -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
