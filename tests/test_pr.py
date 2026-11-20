"""portpilot pr: the build-files contribution (port folder, workflow, README row, PR.md)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from portpilot.pr import Checkout, PrError, add_readme_row, contribute, gh_repo, pr_body, workflow

README = """# QNX ports
| Port | Build |
|---|---|
| [libuv](https://github.com/qnx-ports/build-files/blob/main/ports/libuv/README.md) | b |
| [libxml2](https://github.com/qnx-ports/build-files/blob/main/ports/libxml2/README.md) | b |
| [zlib](https://github.com/qnx-ports/build-files/blob/main/ports/zlib/README.md) | b |

More text.
"""


def test_gh_repo() -> None:
    assert gh_repo("https://github.com/jbeder/yaml-cpp.git") == "jbeder/yaml-cpp"
    assert gh_repo("https://github.com/eclipse-paho/paho.mqtt.c.git") == "eclipse-paho/paho.mqtt.c"
    with pytest.raises(PrError):
        gh_repo("https://gitlab.com/a/b")


def test_readme_row_goes_in_order_once() -> None:
    text = add_readme_row(README, "libwebsockets")
    names = [ln.split("]")[0][3:] for ln in text.splitlines() if ln.startswith("| [")]
    assert names == ["libuv", "libwebsockets", "libxml2", "zlib"]
    assert "actions/workflows/libwebsockets.yml/badge.svg" in text
    assert add_readme_row(text, "libwebsockets") == text
    assert add_readme_row(README, "zstd").splitlines()[6].startswith("| [zstd]")  # last row


def test_workflow_matches_the_official_shape() -> None:
    wf = workflow("yaml-cpp", Checkout("yaml-cpp", "jbeder/yaml-cpp", "yaml-cpp-0.9.0"),
                  [Checkout("muslflt", "qnx-ports/muslflt")], patch=True)
    assert wf.startswith("name: yaml-cpp\n")
    assert "contains(github.event.pull_request.title, 'yaml-cpp')" in wf
    assert '      - "ports/yaml-cpp/**"' in wf and "runs-on: ubuntu-22.04-common" in wf
    # dependency first, then the library at its tag, patched, built with tests
    assert wf.index("repository: qnx-ports/muslflt") < wf.index("repository: jbeder/yaml-cpp")
    assert "          ref: yaml-cpp-0.9.0\n" in wf
    assert "git -C yaml-cpp apply $GITHUB_WORKSPACE/build-files/ports/yaml-cpp/patches/" in wf
    assert ('QNX_PROJECT_ROOT="$(pwd)/muslflt" make -C build-files/ports/muslflt install'
            in wf)
    assert ('BUILD_TESTING="ON" QNX_PROJECT_ROOT="$(pwd)/yaml-cpp" make -C '
            'build-files/ports/yaml-cpp install') in wf
    assert wf.index("Build muslflt") < wf.index("Build yaml-cpp")


def _run(**tt: object) -> dict[str, object]:
    return {"ok": True, "pre_fixes": [
        {"rule": "bsd-sockaddr-len", "kind": "source", "title": "set sin_len on QNX too",
         "reason": "QNX defines neither BSD nor __APPLE__", "path": "src/a.cpp"}],
        "attempts": [{"applied": [{"rule": "link-socket", "kind": "port",
                                   "title": "link -lsocket", "reason": "sockets are in "
                                   "libsocket"}]}],
        "target_tests": tt or None}


def test_pr_body_reports_only_recorded_evidence() -> None:
    spec = {"upstream": "https://github.com/fpagliughi/sockpp.git", "commit": "v1.0.0",
            "has_patch": True}
    body = pr_body("sockpp", spec, _run(passed=1, total=1, cases=[33, 33], results=[],
                                       services=[]))
    assert body.startswith("# Adding sockpp build-files\n")  # the title CI looks for
    assert "**33/33 test cases (1/1 test programs pass)**" in body
    assert "| set sin_len on QNX too (`src/a.cpp`) | QNX defines neither" in body
    assert "| link -lsocket | sockets are in libsocket |" in body
    assert "patches/qnx.patch" in body
    assert "Tested" not in pr_body("sockpp", spec, _run())  # no test run, no claim


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_contribute_commits_port_workflow_and_row(tmp_path: Path) -> None:
    bf = tmp_path / "build-files"
    (bf / "ports" / "Catch2").mkdir(parents=True)
    (bf / "ports" / "Catch2" / "README.md").write_text(
        "git clone https://github.com/qnx-ports/build-files.git\n"
        "git clone -b v3.5.0 https://github.com/qnx-ports/Catch2.git\n")
    (bf / ".github" / "workflows").mkdir(parents=True)
    (bf / "README.md").write_text(README)
    for args in (["init", "-q", "-b", "main"], ["add", "-A"],
                 ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"]):
        subprocess.run(["git", "-C", str(bf), *args], check=True)
    out = tmp_path / "out"
    port = out / "sockpp"
    (port / "nto-x86_64-o" / "build").mkdir(parents=True)
    (port / "nto-x86_64-o" / "build" / "big.o").write_text("x")
    (port / "nto-x86_64-o" / "Makefile").write_text("include ../common.mk\n")
    (port / "common.mk").write_text("# mk\n")
    (out / "spec.json").write_text(json.dumps({
        "name": "sockpp", "upstream": "https://github.com/fpagliughi/sockpp.git",
        "commit": "v1.0.0", "deps": ["Catch2"], "muslflt": False, "has_patch": False}))
    (out / "run.json").write_text(json.dumps(_run()))
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    import os
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        dest = contribute(out, bf, author="Port Author <port@example.org>", check_archs=False)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    log = subprocess.run(["git", "-C", str(dest), "log", "--format=%s", "-1"],
                         capture_output=True, text=True).stdout.strip()
    assert log == "Adding sockpp build-files"
    from portpilot.pr import commit_author

    assert commit_author(dest) == "Port Author <port@example.org>"
    with pytest.raises(PrError, match="Name <email>"):
        contribute(out, bf, author="no email", check_archs=False)
    files = subprocess.run(["git", "-C", str(dest), "show", "--name-only", "--format="],
                           capture_output=True, text=True).stdout.split()
    # the port is re-rendered with the current templates; the build tree is left out
    assert sorted(files) == [".github/workflows/sockpp.yml", "README.md",
                             "ports/sockpp/Makefile", "ports/sockpp/README.md",
                             "ports/sockpp/common.mk", "ports/sockpp/nto-aarch64-le/Makefile",
                             "ports/sockpp/nto-x86_64-o/Makefile",
                             "ports/sockpp/qnx.nto.toolchain.cmake"]
    assert "CMAKE_TOOLCHAIN_FILE" in (dest / "ports/sockpp/common.mk").read_text()
    wf = (dest / ".github/workflows/sockpp.yml").read_text()
    assert "repository: qnx-ports/Catch2" in wf and "          ref: v3.5.0" in wf
    assert (out / "pr" / "PR.md").read_text().startswith("# Adding sockpp build-files")
    # the source checkout is untouched
    assert not (bf / "ports" / "sockpp").exists()


def test_pr_body_lists_every_file_and_test_round_fixes() -> None:
    spec = {"upstream": "https://github.com/jbeder/yaml-cpp.git", "commit": "v1", "has_patch": 1}
    fix = {"rule": "bsd-sockaddr-len", "title": "set sin_len", "reason": "QNX has sin_len"}
    run = _run(passed=1, total=1, cases=[1, 1], results=[])
    run["pre_fixes"] = [{**fix, "path": "src/a.cpp"}, {**fix, "path": "src/b.cpp"},
                        {**fix, "path": "src/a.cpp"}]
    run["test_rounds"] = [{"fixes": [{"rule": "float-format", "test": "yaml-cpp::test",
                                      "evidence": "0.1 vs 0.10000000000000001",
                                      "title": "link muslflt (project_hooks.cmake)"}]}]
    body = pr_body("yaml-cpp", spec, run)
    assert "| set sin_len (`src/a.cpp`, `src/b.cpp`) | QNX has sin_len |" in body
    assert ("| link muslflt (project_hooks.cmake) | yaml-cpp::test failed on QNX: "
            "0.1 vs 0.10000000000000001 |") in body


def test_pr_body_reports_other_architectures() -> None:
    spec = {"upstream": "https://github.com/jbeder/yaml-cpp.git", "commit": "v1"}
    run = _run(passed=1, total=1, cases=[1, 1], results=[])
    run["arch_builds"] = [
        {"arch": "aarch64", "ok": True, "fixes": [
            {"rule": "unsigned-char", "title": "allow negative constants in char (aarch64)",
             "reason": "plain char is unsigned on aarch64"}]},
        {"arch": "x86_64", "ok": True, "recheck": True}]
    body = pr_body("yaml-cpp", spec, run)
    assert "- aarch64: builds with its tests (built, not run)" in body
    assert "| allow negative constants in char (aarch64) | plain char is unsigned" in body
    run["arch_builds"] = [{"arch": "aarch64", "ok": False, "reason": "x.c:1 boom"}]
    assert "- aarch64: not built (`Makefile.dnm`): x.c:1 boom" in pr_body("yaml-cpp", spec, run)
