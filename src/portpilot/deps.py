"""Dependency ports from qnx-ports/build-files: muslflt, and any package an official port
provides (e.g. Catch2 for a library's tests).

An official port is built exactly as its README says: its source is cloned next to
build-files (the workspace layout every port's common.mk expects), then
`make -C build-files/ports/<Name>/nto-<cpu>-o install` installs it into PortPilot's stage,
where the library's own CMake configure finds it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

_CLONE = re.compile(r"git clone\s+(?:(?:-b|--branch)\s+(?P<branch>\S+)\s+)?"
                    r"(?P<url>https://\S+?)(?:\.git)?(?=\s|$)")

MUSLFLT_URL = "https://github.com/qnx-ports/muslflt.git"
# muslflt's port predates the CMake layout: it uses nto-<cpu> folders
_MUSLFLT_DIR = {"x86_64": "nto-x86_64", "aarch64": "nto-aarch64"}


def find_build_files(explicit: str | None = None) -> Path | None:
    for c in (explicit, os.environ.get("PORTPILOT_BUILD_FILES"), "~/qnx-work/build-files",
              "~/build-files"):
        if c and (Path(c).expanduser() / "ports").is_dir():
            return Path(c).expanduser()
    return None


def muslflt_available(stage: Path, env: dict[str, str], arch: str = "x86_64") -> bool:
    roots = [stage / arch, Path(env.get("QNX_TARGET", "/nonexistent")) / arch]
    return any((r / sub / "libmuslflt.a").is_file() for r in roots
               for sub in ("usr/local/lib", "usr/lib", "lib"))


def ensure_muslflt(stage: Path, env: dict[str, str], work: Path, log: Path,
                   build_files: Path | None, arch: str = "x86_64", jobs: int = 8) -> str:
    """Build the muslflt port into the stage if it isn't there. Returns "" or an error."""
    if muslflt_available(stage, env, arch):
        return ""
    if build_files is None:
        return ("muslflt is needed: clone github.com/qnx-ports/build-files and pass "
                "--build-files, or build the muslflt port into the stage yourself")
    src = work / "deps" / "muslflt"
    if not src.is_dir():
        src.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["git", "clone", "-q", "--depth", "1", MUSLFLT_URL, str(src)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return f"cannot clone {MUSLFLT_URL}: {r.stderr.strip()}"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "w") as fh:
        rc = subprocess.run(
            ["make", "-C", str(build_files / "ports" / "muslflt" / _MUSLFLT_DIR[arch]),
             "install", f"JLEVEL={jobs}", f"INSTALL_ROOT_nto={stage}", "USE_INSTALL_ROOT=true",
             f"QNX_PROJECT_ROOT={src}"], stdout=fh, stderr=subprocess.STDOUT, env=env
        ).returncode
    if rc != 0 or not muslflt_available(stage, env, arch):
        return f"building muslflt failed (rc={rc}); see {log}"
    return ""


def official_port(package: str, build_files: Path | None) -> str | None:
    """The build-files port directory name for a CMake package name, if QNX has one."""
    if build_files is None or not package:
        return None
    want = package.lower().replace("_", "-")
    for d in sorted((build_files / "ports").iterdir()):
        if d.is_dir() and d.name.lower().replace("_", "-") == want:
            return d.name
    return None


def port_source(port_dir: Path) -> tuple[str, str] | None:
    """(clone URL, branch or "") of a port's source, from its README's workspace setup."""
    readme = port_dir / "README.md"
    if not readme.is_file():
        return None
    for m in _CLONE.finditer(readme.read_text(encoding="utf-8", errors="replace")):
        if not m.group("url").rstrip("/").endswith("build-files"):
            return m.group("url"), m.group("branch") or ""
    return None


def _changed_tracked(repo: Path) -> set[str]:
    """Tracked files that are deleted or modified in a git checkout (empty if not one)."""
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "-d", "-m"], capture_output=True,
                       text=True, check=False)
    return set(r.stdout.split("\n")) - {""} if r.returncode == 0 else set()


def _tree(root: Path) -> set[str]:
    """Relative paths of the files and links under root."""
    out: set[str] = set()
    for d, _, files in os.walk(root):
        rel = os.path.relpath(d, root)
        out.update(f if rel == "." else f"{rel}/{f}" for f in files)
    return out


def relocate_sdp_writes(qnx_target: Path, stage: Path, before: set[str],
                        t0: float) -> tuple[list[str], list[str]]:
    """Undo an install that went into the SDP instead of the stage (the official mosquitto
    port ignores INSTALL_ROOT_nto). Files it created under $QNX_TARGET move to the same
    place under the stage, which stands in for $QNX_TARGET. Returns (moved, overwritten):
    files that existed before and changed cannot be restored, only reported."""
    moved, overwritten = [], []
    for rel in sorted(_tree(qnx_target)):
        p = qnx_target / rel
        if rel not in before:
            dest = stage / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(dest))
            moved.append(rel)
        elif p.lstat().st_mtime >= t0:
            overwritten.append(rel)
    for rel in moved:  # drop the folders the install created and left empty
        d = (qnx_target / rel).parent
        while d != qnx_target and d.is_dir() and not any(d.iterdir()):
            d.rmdir()
            d = d.parent
    return moved, overwritten


def ensure_port(package: str, stage: Path, env: dict[str, str], log: Path,
                build_files: Path | None, arch: str = "x86_64", jobs: int = 8,
                timeout: float = 3600) -> tuple[str, str]:
    """Build the official port that provides `package` into the stage.

    Returns (port name, "") on success, else (port name or "", reason)."""
    port = official_port(package, build_files)
    if port is None or build_files is None:
        return "", (f"no official QNX port provides {package}"
                    + ("" if build_files else " (pass --build-files to look)"))
    pdir = build_files / "ports" / port
    srcinfo = port_source(pdir)
    if srcinfo is None:
        return port, f"cannot tell where {port}'s source lives (no git clone in its README)"
    url, branch = srcinfo
    src = build_files.parent / port  # where the port's common.mk looks for it
    if not src.is_dir():
        cmd = ["git", "clone", "-q", "--depth", "1", *(["-b", branch] if branch else []),
               f"{url}.git", str(src)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            return port, f"cannot clone {url}: {r.stderr.strip()[:200]}"
    cpu = next((c for c in (f"nto-{arch}-o", f"nto-{arch}") if (pdir / c).is_dir()), None)
    if cpu is None:
        return port, f"{port} has no {arch} build folder"
    log.parent.mkdir(parents=True, exist_ok=True)
    before = _changed_tracked(build_files)
    qt = Path(env["QNX_TARGET"]) if env.get("QNX_TARGET") else None
    sdp_before = _tree(qt) if qt and qt.is_dir() else set()
    t0 = time.time()
    with open(log, "w") as fh:
        try:
            # QNX_PROJECT_ROOT always explicit: some ports' hooks default to ../../.. (the
            # build-files root) and clean it with `rm -f */Makefile ...` (cunit)
            rc = subprocess.run(
                ["make", "-C", str(pdir / cpu), "install", f"JLEVEL={jobs}",
                 f"QNX_PROJECT_ROOT={src}", f"INSTALL_ROOT_nto={stage}",
                 "USE_INSTALL_ROOT=true"],
                stdout=fh, stderr=subprocess.STDOUT, env=env, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            return port, f"building {port} took over {timeout:.0f}s; see {log}"
        finally:
            touched = _changed_tracked(build_files) - before
            if touched:  # never leave the user's build-files checkout damaged
                subprocess.run(["git", "-C", str(build_files), "checkout", "--", *touched],
                               capture_output=True, check=False)
                fh.write(f"\nportpilot: the {port} build changed {len(touched)} tracked "
                         "build-files file(s); restored them from git\n")
            if sdp_before and qt is not None:  # never leave files in the user's SDP
                moved, over = relocate_sdp_writes(qt, stage, sdp_before, t0)
                if moved:
                    fh.write(f"\nportpilot: the {port} port installed {len(moved)} file(s) "
                             "into $QNX_TARGET, not the stage; moved them to the stage\n")
                if over:
                    fh.write(f"\nportpilot: WARNING the {port} build changed {len(over)} "
                             "existing file(s) in $QNX_TARGET: " + ", ".join(over[:20]) + "\n")
    if rc != 0:
        return port, f"building the official {port} port failed (rc={rc}); see {log}"
    return port, ""
