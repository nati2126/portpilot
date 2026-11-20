"""Self-contained HTML report for one port run (no external assets; opens offline).

    portpilot report <output-dir>      # writes <output-dir>/report.html

Shows the verdict, every change with its reason and evidence (rule + cited source, or AI +
the rebuild that verified it), the build attempts, the AI log including rejected edits, the
dependency matrix, the tests on QNX and the final patch.
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from . import __version__
from . import kb as kb_mod
from .kb import KnowledgeBase

CSS = """
:root{--bg:#f7f8fa;--card:#fff;--ink:#1b1f24;--mute:#5b6570;--line:#e3e6ea;--accent:#2557d6;
--ok:#16794a;--okbg:#e5f5ec;--bad:#b42318;--badbg:#fdeceb;--warn:#8a5a00;--warnbg:#fff4dc;
--ai:#6b3fb8;--aibg:#f1eafc;--code:#f2f4f7;--add:#e6f6ea;--del:#fdecec}
@media (prefers-color-scheme:dark){:root{--bg:#0f1216;--card:#171b21;--ink:#e6e9ee;--mute:#9aa4b0;
--line:#2a3038;--accent:#7aa2ff;--ok:#5fd394;--okbg:#14301f;--bad:#ff8a80;--badbg:#3a1714;
--warn:#f2c46b;--warnbg:#36290c;--ai:#c4a5ff;--aibg:#2a1f3d;--code:#1e232b;--add:#15301d;
--del:#3a1a1a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 16px 60px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:34px 0 10px}
a{color:var(--accent)}.mute{color:var(--mute)}
.top{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between}
.pill{display:inline-block;padding:4px 12px;border-radius:999px;font-weight:600;font-size:14px}
.ok{background:var(--okbg);color:var(--ok)}.bad{background:var(--badbg);color:var(--bad)}
.warn{background:var(--warnbg);color:var(--warn)}.ai{background:var(--aibg);color:var(--ai)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin-top:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card b{display:block;font-size:24px}.card span{color:var(--mute);font-size:13px}
.flow{display:flex;flex-wrap:wrap;gap:6px;margin-top:16px;font-size:13px}
.flow span{padding:3px 10px;border-radius:6px;border:1px solid var(--line);background:var(--card)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
border-radius:10px;overflow:hidden;font-size:14px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute)}
tr:last-child td{border-bottom:0}
code,pre{font:13px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace}
code{background:var(--code);padding:1px 5px;border-radius:4px}
pre{background:var(--code);padding:12px;border-radius:8px;overflow:auto;margin:0}
.diff span{display:block}.diff .a{background:var(--add)}.diff .d{background:var(--del)}
.diff .h{color:var(--accent)}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;
margin:8px 0}summary{cursor:pointer;font-weight:600}
.scroll{overflow-x:auto}
footer{margin-top:40px;font-size:13px;color:var(--mute)}
"""


def _e(s: Any) -> str:
    return html.escape(str(s), quote=True)


def _src_link(kb: KnowledgeBase, rule_id: str) -> str:
    if rule_id not in kb.rules:
        return _e(rule_id)
    links = []
    for s in kb.rule(rule_id).sources:
        src = kb.sources[s]
        url = src.url
        if url.startswith("http"):
            links.append(f'<a href="{_e(url)}">{_e(src.title)}</a>')
        else:
            links.append(_e(src.title))
    return f"<code>{_e(rule_id)}</code> · " + ", ".join(links)


def _changes(run: dict[str, Any], kb: KnowledgeBase) -> list[tuple[str, str, str, str]]:
    """(origin, what, why, evidence) for every kept change."""
    rows: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    fixes = [*run.get("pre_fixes", []), *(f for a in run.get("attempts", [])
                                          for f in a.get("applied", []))]
    for f in fixes:
        if f.get("rule") == "ai":
            continue  # listed from the AI log with its verification
        kind = f.get("kind")
        where = (f"<code>{_e(f['path'])}:{_e(f['line'])}</code>" if kind == "source" else
                 "" if kind == "dep" else
                 f"<code>{_e(f.get('setting', ''))}</code> in common.mk")
        key = (f.get("rule", ""), where)
        if key in seen:
            continue
        seen.add(key)
        rows.append(("rule", f"{_e(f['title'])}<br>{where}", _e(f.get("reason", "")),
                     _src_link(kb, f.get("rule", ""))))
    for a in run.get("ai", []):
        if a.get("result") != "accepted":
            continue
        files = sorted({e["path"] for e in a.get("edits", [])})
        rows.append(("AI", f"edit in {', '.join(f'<code>{_e(p)}</code>' for p in files)}",
                     f"build error: <code>{_e(a['error'])}</code>",
                     f"{_e(a['model'])} (local) · kept because {_e(a.get('reason', ''))}"))
    for r in run.get("test_rounds", []):
        for f in r.get("fixes", []):
            rows.append(("test" if f.get("rule") != "ai-test-repair" else "AI",
                         _e(f.get("title", "")),
                         f"test <code>{_e(f.get('test', ''))}</code> failed on QNX"
                         + (f": {_e(f['evidence'])[:160]}" if f.get("evidence") else ""),
                         _src_link(kb, f["rule"]) if f.get("rule") in kb.rules
                         else _e(f.get("rule", ""))))
    return rows


def _diff_html(patch: str) -> str:
    out = []
    for ln in patch.splitlines():
        cls = ("h" if ln.startswith(("@@", "diff ")) else
               "a" if ln.startswith("+") and not ln.startswith("+++") else
               "d" if ln.startswith("-") and not ln.startswith("---") else "c")
        out.append(f'<span class="{cls}">{_e(ln) or " "}</span>')
    return '<pre class="diff">' + "".join(out) + "</pre>"


def _matrix_html(matrix: dict[str, Any], fixed: set[str] | None = None) -> str:
    """`fixed`: rules PortPilot applied in this run; their rows read "fixed by rule"."""
    rows = matrix.get("matrix", [])
    if not rows:
        return '<p class="mute">The scan found no Linux-only dependencies.</p>'
    body = []
    for r in rows:
        st = r["status"]
        if st == "needs work" and r.get("rule") in (fixed or set()):
            st = "fixed by rule"
        cls = "warn" if st == "needs work" else "ok" if st in ("guarded", "fixed by rule") else ""
        where = ", ".join(f"<code>{_e(o['path'])}:{_e(o['line'])}</code>"
                          for o in r["occurrences"][:2])
        body.append(f"<tr><td><b>{_e(r['dependency'])}</b><br><span class=mute>"
                    f"{_e(r['category'])}</span></td><td>{_e(r['linux_standard'])}</td>"
                    f"<td>{_e(r['qnx_equivalent'])}</td><td>{_e(r['porting_strategy'])}</td>"
                    f"<td>{_e(r['auto_fixable'])}</td><td><span class='pill {cls}'>{_e(st)}"
                    f"</span><br>{where}</td></tr>")
    return ("<div class=scroll><table><tr><th>Dependency</th><th>Linux</th><th>QNX 8.0</th>"
            "<th>Strategy</th><th>Auto-fix</th><th>Status</th></tr>" + "".join(body)
            + "</table></div>")


def render_html(out: Path, kb: KnowledgeBase | None = None) -> str:
    kb = kb or kb_mod.load()
    run: dict[str, Any] = json.loads((out / "run.json").read_text(encoding="utf-8"))
    matrix: dict[str, Any] = {}
    if (out / "matrix.json").exists():
        matrix = json.loads((out / "matrix.json").read_text(encoding="utf-8"))
    port_dir = Path(run["port_dir"])
    patch_f = port_dir / "patches" / "qnx.patch"
    patch = patch_f.read_text(encoding="utf-8", errors="replace") if patch_f.exists() else ""
    tt = run.get("target_tests") or {}
    attempts = run.get("attempts", [])
    ai = run.get("ai", [])

    cases = tt.get("cases")
    tests_txt = (f"{cases[0]}/{cases[1]} test cases pass on QNX" if cases else
                 f"{tt.get('passed')}/{tt.get('total')} tests pass on QNX")
    if run.get("ok") and tt.get("ok"):
        verdict, vcls = f"Ported · {tests_txt}", "ok"
    elif run.get("ok") and tt:
        verdict, vcls = f"Built · {tests_txt}", "warn"
    elif run.get("ok") and run.get("tests_skipped"):
        verdict, vcls = "Built for QNX · library only, tests not built", "warn"
    elif run.get("ok"):
        verdict, vcls = "Built for QNX · not tested on a target yet", "warn"
    else:
        verdict, vcls = "Not built: needs a person", "bad"

    changes = _changes(run, kb)
    n_rule = sum(1 for c in changes if c[0] == "rule")
    n_ai = sum(1 for c in changes if c[0] == "AI")
    n_rej = sum(1 for a in ai if a.get("result") in ("rejected", "invalid"))
    up = run.get("upstream") or run.get("source", "")
    up_html = (f'<a href="{_e(up.removesuffix(".git"))}">{_e(up.removesuffix(".git"))}</a>'
               if up.startswith("http") else f"<code>{_e(up)}</code>")
    commit = f" @ <code>{_e(run['commit'][:10])}</code>" if run.get("commit") else ""

    h = [f"<!doctype html><html lang=en><head><meta charset=utf-8>"
         f"<meta name=viewport content='width=device-width,initial-scale=1'>"
         f"<title>PortPilot · {_e(run['name'])}</title><style>{CSS}</style></head><body><main>",
         "<div class=top><div>",
         f"<div class=mute>PortPilot report · QNX 8.0 · x86_64</div><h1>{_e(run['name'])}</h1>",
         f"<div class=mute>{up_html}{commit}</div></div>",
         f"<span class='pill {vcls}'>{_e(verdict)}</span></div>",
         "<div class=cards>",
         f"<div class=card><b>{len(attempts)}</b><span>build attempt(s), "
         f"{_e(run.get('elapsed_s', 0))} s</span></div>",
         f"<div class=card><b>{n_rule}</b><span>changes by rule (each cites a source)</span></div>",
         f"<div class=card><b>{n_ai}</b><span>AI edits kept · {n_rej} rejected by the "
         "build</span></div>",
         (f"<div class=card><b>{_e(cases[0])}/{_e(cases[1])}</b><span>test cases pass on QNX, "
          f"in {_e(tt['passed'])}/{_e(tt['total'])} passing programs</span></div>" if cases else
          f"<div class=card><b>{_e(tt['passed'])}/{_e(tt['total'])}</b><span>test programs pass "
          f"on QNX ({_e(tt['host'])})</span></div>" if tt else
          "<div class=card><b>–</b><span>not run on a QNX target</span></div>"),
         "</div>"]

    flow = ["scan", "scaffold"] + [f"build {a['n']}: {'ok' if a['ok'] else a['phase']}"
                                   for a in attempts]
    if tt:
        flow.append(f"QNX tests: {cases[0]}/{cases[1]} cases" if cases else
                    f"QNX tests: {tt['passed']}/{tt['total']}")
    h.append("<div class=flow>" + "".join(f"<span>{_e(s)}</span>" for s in flow) + "</div>")

    h.append("<h2>What PortPilot changed, and why</h2>")
    if changes:
        h.append("<div class=scroll><table><tr><th>By</th><th>Change</th><th>Why</th>"
                 "<th>Evidence</th></tr>")
        for origin, what, why, ev in changes:
            cls = "ai" if origin == "AI" else "ok"
            h.append(f"<tr><td><span class='pill {cls}'>{_e(origin)}</span></td><td>{what}</td>"
                     f"<td>{why}</td><td>{ev}</td></tr>")
        h.append("</table></div>")
    else:
        h.append('<p class="mute">No changes were needed.</p>')

    if run.get("tests_skipped"):
        h.append(f"<p class='pill warn'>{_e(run['tests_skipped'])}</p>")

    if run.get("scan_warnings"):
        h.append("<h2>Needs a person's review</h2><div class=scroll><table>"
                 "<tr><th>Issue</th><th>Where</th><th>Source</th></tr>")
        for w in run["scan_warnings"]:
            h.append(f"<tr><td>{_e(w['title'])}</td><td><code>{_e(w['where'])}</code></td>"
                     f"<td>{_src_link(kb, w['rule'])}</td></tr>")
        h.append("</table></div>")

    unfixed = attempts[-1].get("unfixed", []) if attempts and not run.get("ok") else []
    if unfixed:
        h.append("<h2>Left for a person</h2><div class=scroll><table>"
                 "<tr><th>Error</th><th>Hint</th></tr>")
        for u in unfixed:
            h.append(f"<tr><td><code>{_e(u['location'])}</code><br>{_e(u['message'])}</td>"
                     f"<td>{_e(u['hint'])}"
                     + (f"<br>{_src_link(kb, u['rule'])}" if u.get("rule") in kb.rules else "")
                     + "</td></tr>")
        h.append("</table></div>")

    if tt.get("results"):
        h.append(f"<h2>Tests on QNX 8.0 ({_e(tt['host'])})</h2><div class=scroll><table>"
                 "<tr><th>Test</th><th>Result</th><th>Seconds</th></tr>")
        for r in tt["results"]:
            cls = "ok" if r["status"] == "PASS" else "bad"
            h.append(f"<tr><td><code>{_e(r['name'])}</code></td><td><span class='pill {cls}'>"
                     f"{_e(r['status'])}</span></td><td>{_e(r['seconds'])}</td></tr>")
        h.append("</table></div>")

    h.append("<h2>Build attempts</h2><div class=scroll><table><tr><th>#</th><th>Result</th>"
             "<th>First error</th><th>Fixed by rule</th></tr>")
    for a in attempts:
        first = a["errors"][0] if a.get("errors") else None
        err = ""
        if first:
            loc = Path(first["file"]).name + (f":{first['line']}" if first["line"] else "")
            err = f"<code>{_e(loc)}</code> {_e(first['message'])}"
        fixed = "<br>".join(_e(f["title"]) for f in a.get("applied", []) if f.get("rule") != "ai")
        res = ("<span class='pill ok'>built</span>" if a["ok"] else
               f"<span class='pill bad'>{_e(a['phase'])}: {len(a.get('errors', []))} errors"
               "</span>")
        h.append(f"<tr><td>{_e(a['n'])}</td><td>{res}</td><td>{err}</td><td>{fixed}</td></tr>")
    h.append("</table></div>")

    if ai:
        h.append("<h2>AI log (local model, every edit verified by a rebuild)</h2>"
                 "<div class=scroll><table><tr><th>#</th><th>Error</th><th>Result</th>"
                 "<th>Reason</th></tr>")
        for a in ai:
            res = a.get("result", "")
            cls = {"accepted": "ok", "rejected": "bad", "invalid": "bad"}.get(res, "warn")
            h.append(f"<tr><td>{_e(a['n'])}</td><td><code>{_e(a['error'])}</code></td>"
                     f"<td><span class='pill {cls}'>{_e(res)}</span></td>"
                     f"<td>{_e(a.get('reason', ''))}</td></tr>")
        h.append("</table></div>")

    if matrix:
        h.append("<h2>Dependency matrix</h2>")
        applied = {f.get("rule") for f in [
            *run.get("pre_fixes", []), *(f for a in run.get("attempts", [])
                                         for f in a.get("applied", [])),
            *(f for t in run.get("test_rounds") or [] for f in t.get("fixes", []))]}
        h.append(_matrix_html(matrix, {r for r in applied if r}))

    if patch:
        h.append(f"<h2>Source patch</h2><p class=mute>{_e(run.get('patch_stat', ''))} · "
                 "shipped as <code>patches/qnx.patch</code></p>")
        h.append(_diff_html(patch))

    h.append(f"<footer>Generated {datetime.now():%Y-%m-%d %H:%M} by PortPilot {__version__}. "
             "Port folder in the qnx-ports/build-files layout: "
             f"<code>{_e(port_dir)}</code>. AI ran locally; nothing left this machine."
             "</footer></main></body></html>")
    return "\n".join(h)


def write_report(out: Path, kb: KnowledgeBase | None = None) -> Path:
    p = out / "report.html"
    p.write_text(render_html(out, kb), encoding="utf-8")
    return p
