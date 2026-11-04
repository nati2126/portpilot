"""Dependency ports from qnx-ports/build-files that a fix may need (today: muslflt)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

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
