"""report.html from a recorded run (synthetic run.json; no QNX needed)."""

from __future__ import annotations

import json
from pathlib import Path

from portpilot.kb import KnowledgeBase
from portpilot.report import render_html


def make_run(tmp_path: Path) -> Path:
    port = tmp_path / "demo"
    (port / "patches").mkdir(parents=True)
    (port / "patches" / "qnx.patch").write_text(
        "diff --git a/src/net.c b/src/net.c\n@@ -1,2 +1,5 @@\n #include <x.h>\n"
        "+#ifndef MSG_MORE\n+#define MSG_MORE 0\n+#endif\n-old <tag>\n")
    run = {
        "name": "demo", "source": "https://github.com/acme/demo.git",
        "upstream": "https://github.com/acme/demo.git", "commit": "0123456789abcdef",
        "port_dir": str(port), "ok": True, "elapsed_s": 12.5, "patch_stat": "1 file changed",
        "pre_fixes": [],
        "attempts": [
            {"n": 1, "ok": False, "phase": "link",
             "errors": [{"file": "/w/libdemo.so", "line": 0,
                         "message": "undefined reference to 'send'"}],
             "applied": [{"rule": "link-socket", "kind": "port", "title": "link -lsocket",
                          "reason": "send is in libsocket", "setting": "-lsocket"},
                         {"rule": "optional-flag", "kind": "source", "title": "define MSG_MORE",
                          "reason": "hint only", "path": "src/net.c", "line": 3}],
             "unfixed": []},
            {"n": 2, "ok": True, "phase": "", "errors": [], "applied": [], "unfixed": []}],
        "ai": [{"n": 1, "error": "src/dir.c:15: no member d_type", "model": "qwen2.5-coder:7b",
                "result": "accepted", "reason": "rebuild ok",
                "edits": [{"path": "src/dir.c", "search": "a", "replace": "b"}]},
               {"n": 2, "error": "src/x.c:1: oops", "model": "qwen2.5-coder:7b",
                "result": "rejected", "reason": "new errors: <script>"}],
        "target_tests": {"host": "192.168.122.202", "ok": True, "passed": 2, "total": 2,
                         "results": [{"name": "t1", "status": "PASS", "seconds": 1},
                                     {"name": "t2", "status": "PASS", "seconds": 0}]},
    }
    (tmp_path / "run.json").write_text(json.dumps(run))
    return tmp_path


def test_report_shows_verdict_changes_and_evidence(tmp_path: Path, kb: KnowledgeBase) -> None:
    text = render_html(make_run(tmp_path), kb)
    assert "Ported · 2/2 tests pass on QNX" in text
    assert "link -lsocket" in text and "<code>-lsocket</code> in common.mk" in text
    assert "<code>src/net.c:3</code>" in text
    assert "1 rejected by the build" in text  # rejected AI edits are shown, not hidden
    assert "<code>libdemo.so</code> undefined reference" in text  # no ':0' for link errors
    assert "&lt;script&gt;" in text and "<script>" not in text  # model text is escaped
    assert '<span class="a">+#define MSG_MORE 0</span>' in text
    assert "https://github.com/acme/demo" in text and "0123456789" in text


def test_failed_run_lists_what_is_left(tmp_path: Path, kb: KnowledgeBase) -> None:
    out = make_run(tmp_path)
    run = json.loads((out / "run.json").read_text())
    run["ok"] = False
    run.pop("target_tests")
    run["attempts"][-1] = {"n": 2, "ok": False, "phase": "compile", "errors": [],
                           "applied": [],
                           "unfixed": [{"location": "src/ev.c:9", "message": "epoll.h missing",
                                        "rule": "epoll", "hint": "use poll() or ionotify"}]}
    (out / "run.json").write_text(json.dumps(run))
    text = render_html(out, kb)
    assert "Not built: needs a person" in text
    assert "Left for a person" in text and "use poll() or ionotify" in text


def test_matrix_row_fixed_by_an_applied_rule() -> None:
    from portpilot.report import _matrix_html
    m = {"matrix": [{"dependency": "socket API lives in libsocket", "category": "Linking",
                     "linux_standard": "libc", "qnx_equivalent": "libsocket",
                     "porting_strategy": "link -lsocket", "auto_fixable": "yes",
                     "status": "needs work", "rule": "link-socket", "occurrences": []}]}
    assert "needs work" in _matrix_html(m)
    html = _matrix_html(m, {"link-socket"})
    assert "fixed by rule" in html and "needs work" not in html
