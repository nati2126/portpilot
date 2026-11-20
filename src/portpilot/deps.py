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


CPUVARDIR = {"x86_64": "x86_64", "aarch64": "aarch64le"}  # QNX's install folder per arch


def muslflt_available(stage: Path, env: dict[str, str], arch: str = "x86_64") -> bool:
    d = CPUVARDIR.get(arch, arch)
    roots = [stage / d, Path(env.get("QNX_TARGET", "/nonexistent")) / d]
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
    names = [PACKAGE_PORTS.get(want, want), want, f"lib{want}"]  # find_package(PNG) -> libpng
    ports = {d.name.lower().replace("_", "-"): d.name
             for d in (build_files / "ports").iterdir() if d.is_dir()}
    return next((ports[n] for n in names if n in ports), None)


# CMake find_package() names whose official QNX port has another name
PACKAGE_PORTS = {"jpeg": "libjpeg-turbo", "expat": "libexpat", "gtest": "googletest",
                 "gmock": "googletest"}


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


def cpu_dir(port_dir: Path, arch: str) -> str | None:
    """The port's build folder for arch: nto-x86_64-o / nto-aarch64-le in most official
    ports (129 and 132 of them), plain nto-<arch> in a few (muslflt)."""
    return next((c for c in (f"nto-{arch}-o", f"nto-{arch}-le", f"nto-{arch}")
                 if (port_dir / c).is_dir()), None)


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
                timeout: float = 3600, header: str = "") -> tuple[str, str]:
    """Build the official port that provides `package` into the stage. `header`: the
    include that was missing; staged from the port's tree if the port does not install it.

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
    cpu = cpu_dir(pdir, arch)
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
            proot = f"QNX_PROJECT_ROOT={src}"
            # from a clean folder: cunit sets DESTDIR only when it configures, so a second
            # build into a new stage installs to /x86_64
            subprocess.run(["make", "-C", str(pdir / cpu), "clean", proot], stdout=fh,
                           stderr=subprocess.STDOUT, env=env, timeout=600, check=False)
            rc = subprocess.run(
                ["make", "-C", str(pdir / cpu), "install", f"JLEVEL={jobs}",
                 proot, f"INSTALL_ROOT_nto={stage}",
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
    if header and (got := stage_headers(header, stage, [src, pdir / cpu])):
        with open(log, "a") as fh:
            fh.write(f"\nportpilot: the {port} port installs no <{header}>; copied "
                     f"{len(got)} header(s) from its source and build folders to the stage\n")
    return port, ""


def stage_headers(header: str, stage: Path, roots: list[Path]) -> list[Path]:
    """Copy the headers next to `header` into stage/usr/include when a port built the
    library but did not install them (cunit installs with `make install-exec` only, so
    <CUnit/CUnit.h> is missing). Later roots win: the build folder holds headers that
    configure generated (CUnit.h from CUnit.h.in). Returns the files copied."""
    rel = Path(header)
    dest = stage / "usr" / "include" / rel.parent
    if any(p.as_posix().endswith("/" + rel.as_posix()) for p in stage.rglob(rel.name)):
        return []  # installed by the port
    copied: dict[str, Path] = {}
    for root in roots:  # the source tree may hold only CUnit.h.in
        found = [*root.rglob(rel.name), *root.rglob(rel.name + ".in")] if root.is_dir() else []
        for f in sorted(found):
            if not f.is_file():
                continue
            dest.mkdir(parents=True, exist_ok=True)
            for h in f.parent.glob("*.h"):
                shutil.copy2(h, dest / h.name)
                copied[h.name] = dest / h.name
    return list(copied.values())
