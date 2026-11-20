"""Turn a verified port into a qnx-ports/build-files contribution.

A port PR in build-files adds three things (e.g. #327 libwebsockets, #298 onnxruntime):
ports/<name>/, .github/workflows/<name>.yml, and one row in the README's port table. This
module writes all three into a local clone of build-files, commits them on a branch and
writes PR.md with the evidence from the QNX test run. It never pushes.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .deps import MUSLFLT_URL, port_source


class PrError(Exception):
    pass


@dataclass(frozen=True)
class Checkout:
    name: str  # also the path the workflow checks it out to
    repo: str  # owner/name on GitHub
    ref: str = ""


_GH = re.compile(r"github\.com[/:](?P<repo>[\w.-]+/[\w.-]+?)(?:\.git)?/?$")


def gh_repo(url: str) -> str:
    m = _GH.search(url.strip())
    if not m:
        raise PrError(f"not a GitHub repository URL: {url}")
    return m.group("repo")


def dependency_checkouts(spec: dict[str, Any], build_files: Path) -> list[Checkout]:
    """The official ports this port builds first (muslflt, then its deps), with the source
    each port's README clones."""
    out = [Checkout("muslflt", gh_repo(MUSLFLT_URL))] if spec.get("muslflt") else []
    for dep in spec.get("deps") or []:
        src = port_source(build_files / "ports" / dep)
        if src is None:
            raise PrError(f"cannot tell where the {dep} port's source lives "
                          f"(no git clone in ports/{dep}/README.md)")
        out.append(Checkout(dep, gh_repo(src[0]), src[1]))
    return out


def _checkout_step(c: Checkout) -> list[str]:
    lines = [f"      - name: Checkout {c.name}",
             "        uses: actions/checkout@v4",
             "        with:",
             f"          repository: {c.repo}",
             f"          path: {c.name}"]
    return lines + ([f"          ref: {c.ref}"] if c.ref else []) + [""]


def _build_step(name: str, testing: bool) -> list[str]:
    env = 'BUILD_TESTING="ON" ' if testing else ""
    return [f"      - name: Build {name}",
            "        shell: bash",
            "        run: |",
            "          source ~/qnx/800/qnxsdp-env.sh",
            f'          {env}QNX_PROJECT_ROOT="$(pwd)/{name}" make -C build-files/ports/{name}'
            " install",
            ""]


def workflow(name: str, source: Checkout, deps: list[Checkout], patch: bool) -> str:
    """The CI workflow, in the shape of the repo's own port workflows (libwebsockets.yml):
    it runs for pushes to main, manual runs, and PRs whose title names the port."""
    paths = [f'      - ".github/workflows/{name}.yml"', f'      - "ports/{name}/**"']
    lines = [f"name: {name}", "", "permissions:", "  contents: write", "  checks: write", "",
             "on:", "  workflow_dispatch:",
             "  push:", "    branches:", "      - main", "    paths:", *paths,
             "  pull_request:", "    branches:", "      - main", "    paths:", *paths, "",
             "jobs:", "  build:", "    strategy:", "      fail-fast: false", "      matrix:",
             '        qnx_env: ["800"]', "    runs-on: ubuntu-22.04-common", "    if: |",
             "      ((github.event_name == 'workflow_dispatch') ||",
             "      (github.event_name == 'push' && github.ref == 'refs/heads/main') ||",
             "      (github.event_name == 'pull_request' && "
             f"contains(github.event.pull_request.title, '{name}')))",
             "    steps:",
             "      - name: Checkout build-files", "        uses: actions/checkout@v4",
             "        with:", "          path: build-files", ""]
    for c in [*deps, source]:
        lines += _checkout_step(c)
    if patch:
        lines += [f"      - name: Apply the QNX patch to {name}", "        shell: bash",
                  f"        run: git -C {name} apply "
                  f"$GITHUB_WORKSPACE/build-files/ports/{name}/patches/qnx.patch", ""]
    for c in deps:
        lines += _build_step(c.name, testing=False)
    lines += _build_step(name, testing=True)
    return "\n".join(lines).rstrip("\n") + "\n"


_ROW = re.compile(r"^\| \[(?P<name>[^\]]+)\]\(https://github\.com/qnx-ports/build-files/"
                  r"blob/main/ports/")


def readme_row(name: str) -> str:
    base = "https://github.com/qnx-ports/build-files"
    return (f"| [{name}]({base}/blob/main/ports/{name}/README.md) | "
            f"[![Build]({base}/actions/workflows/{name}.yml/badge.svg)]"
            f"({base}/actions/workflows/{name}.yml) |")


def add_readme_row(text: str, name: str) -> str:
    """Insert the port's row into the README's port table before the first row that sorts
    after it (case-insensitive), or after the last row."""
    lines = text.splitlines(keepends=True)
    rows = [i for i, ln in enumerate(lines) if _ROW.match(ln)]
    if not rows:
        raise PrError("README.md has no port table")
    for i in rows:
        m = _ROW.match(lines[i])
        assert m
        if m.group("name").lower() == name.lower():
            return text  # already listed
        if m.group("name").lower() > name.lower():
            lines.insert(i, readme_row(name) + "\n")
            return "".join(lines)
    lines.insert(rows[-1] + 1, readme_row(name) + "\n")
    return "".join(lines)


def _fixes(run: dict[str, Any]) -> list[dict[str, Any]]:
    """One entry per (rule, title), with every file it changed, including test-round fixes."""
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for f in [*run.get("pre_fixes", []),
              *(f for a in run.get("attempts", []) for f in a.get("applied", [])),
              *(f for t in run.get("test_rounds") or [] for f in t.get("fixes", []))]:
        e = seen.setdefault((f.get("rule", ""), f.get("title", "")),
                            {**f, "paths": [], "reason": f.get("reason")
                             or (f"{f['test']} failed on QNX: {f['evidence']}"
                                 if f.get("evidence") else "")})
        if f.get("path") and f["path"] not in e["paths"]:
            e["paths"].append(f["path"])
    return list(seen.values())


def pr_body(name: str, spec: dict[str, Any], run: dict[str, Any]) -> str:
    """PR title line and description, built only from what the run recorded."""
    tt = run.get("target_tests") or {}
    lines = [f"# Adding {name} build-files", "",
             f"Build files for [{name}]({spec['upstream'].removesuffix('.git')}) "
             f"`{spec['commit']}`, from upstream with no fork.", ""]
    if tt:
        res = f"{tt['passed']}/{tt['total']} test programs pass"
        if tt.get("cases"):
            res = f"{tt['cases'][0]}/{tt['cases'][1]} test cases ({res})"
        lines += ["## Tested", "",
                  f"- QNX SDP 8.0, x86_64, QEMU target (mkqnximage): **{res}**."]
        bad = [r["name"] for r in tt.get("results", []) if r.get("status") != "PASS"]
        if bad:
            lines.append(f"- Failing: {', '.join(bad[:20])}" + (" ..." if len(bad) > 20 else ""))
        for s in tt.get("services") or []:
            lines.append(f"- The tests ran against `{s}` on the same QNX target.")
        lines += ["- Run them with `ports/" + name + "/qnxtests.sh` (see the port README).", ""]
    deps = (["muslflt"] if spec.get("muslflt") else []) + list(spec.get("deps") or [])
    if deps:
        lines += ["## Dependencies", "",
                  "Built first from their build-files ports (the workflow does this): "
                  + ", ".join(f"`{d}`" for d in deps) + "."]
        if spec.get("muslflt"):
            lines.append("- `muslflt`: the tests expect glibc-style float formatting; QNX libc "
                         "prints valid but different digits.")
        lines.append("")
    fixes = _fixes(run)
    if fixes:
        lines += ["## QNX changes", "", "| Change | Why |", "|---|---|"]
        for f in fixes:
            where = f" ({', '.join(f'`{p}`' for p in f['paths'])})" if f["paths"] else ""
            lines.append(f"| {f['title']}{where} | {f['reason']} |")
        lines.append("")
    if spec.get("has_patch"):
        lines += [f"Source changes are in `ports/{name}/patches/qnx.patch`; the workflow "
                  "applies it after checking out upstream.", ""]
    lines += ["## Checklist", "",
              f"- [x] `ports/{name}/` with `Makefile`, `common.mk`, `nto-*/Makefile`, "
              "`qnx.nto.toolchain.cmake`, `README.md`",
              f"- [x] `.github/workflows/{name}.yml` (runs when the PR title names `{name}`)",
              "- [x] Row in the README port table", "",
              "Generated with PortPilot and checked by hand.", ""]
    return "\n".join(lines)


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                       env=env)
    if r.returncode != 0:
        raise PrError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


_AUTHOR = re.compile(r"^([^<>]+)<([^<>@\s]+@[^<>\s]+)>$")


def commit_author(repo: Path) -> str:
    """'Name <email>' of the last commit in repo."""
    return _git(repo, "log", "-1", "--format=%an <%ae>").strip()


def contribute(out: Path, build_files: Path, dest: Path | None = None,
               author: str = "") -> Path:
    """Write the contribution for the port in `out` (a `portpilot port` output directory)
    into a fresh local clone of `build-files` at dest (default out/pr/build-files), commit it
    on branch add-<name>, and write out/pr/PR.md. Returns the clone."""
    if not (out / "spec.json").is_file() or not (out / "run.json").is_file():
        raise PrError(f"{out} is not a `portpilot port` output directory (no spec.json/run.json)")
    spec = json.loads((out / "spec.json").read_text(encoding="utf-8"))
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    name = spec["name"]
    port = out / name
    if not (port / "common.mk").is_file():
        raise PrError(f"{port} is not a generated port (no common.mk)")
    if not run.get("ok"):
        raise PrError(f"{name} did not build; nothing to contribute")
    if author and not _AUTHOR.match(author.strip()):
        raise PrError(f"--author wants 'Name <email>', got {author!r}")
    deps = dependency_checkouts(spec, build_files)
    dest = dest or out / "pr" / "build-files"
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["git", "clone", "-q", "--local", str(build_files), str(dest)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise PrError(f"cannot clone {build_files}: {r.stderr.strip()}")
    _git(dest, "checkout", "-q", "-b", f"add-{name}")
    target = dest / "ports" / name
    if target.exists():
        raise PrError(f"build-files already has ports/{name}")
    shutil.copytree(port, target, ignore=shutil.ignore_patterns("build"))
    source = Checkout(name, gh_repo(spec["upstream"]), spec.get("commit", ""))
    wf = dest / ".github" / "workflows" / f"{name}.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(workflow(name, source, deps, bool(spec.get("has_patch"))),
                  encoding="utf-8", newline="\n")
    readme = dest / "README.md"
    readme.write_text(add_readme_row(readme.read_text(encoding="utf-8"), name),
                      encoding="utf-8", newline="\n")
    _git(dest, "add", "-A")
    env = None
    if author:  # through the environment: it beats any git config or inherited GIT_* vars
        m = _AUTHOR.match(author.strip())
        if not m:
            raise PrError(f"--author wants 'Name <email>', got {author!r}")
        n, e = m.group(1).strip(), m.group(2)
        env = {**os.environ, "GIT_AUTHOR_NAME": n, "GIT_AUTHOR_EMAIL": e,
               "GIT_COMMITTER_NAME": n, "GIT_COMMITTER_EMAIL": e}
    _git(dest, "commit", "-q", "-m", f"Adding {name} build-files", env=env)
    body = pr_body(name, spec, run)
    (dest.parent / "PR.md").write_text(body, encoding="utf-8", newline="\n")
    return dest
