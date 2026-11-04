"""Build a generated port with the user's QNX SDP (qcc via the port's own common.mk)."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .diagnostics import ParsedLog, parse
from .scaffold import ARCH_DIRS


class BuildError(RuntimeError):
    pass


def sdp_env(sdp_root: Path | None = None) -> dict[str, str]:
    """The environment with QNX_HOST/QNX_TARGET set, sourcing qnxsdp-env.sh if needed."""
    env = dict(os.environ)
    if env.get("QNX_HOST") and env.get("QNX_TARGET"):
        return env
    root = sdp_root or Path(env.get("QNX_SDP", "~/qnx800")).expanduser()
    script = root / "qnxsdp-env.sh"
    if not script.is_file():
        raise BuildError(f"QNX SDP not found: source qnxsdp-env.sh first (looked for {script})")
    r = subprocess.run(["bash", "-c", 'source "$1" >/dev/null 2>&1 && env -0', "_", str(script)],
                       capture_output=True, check=True)
    for item in r.stdout.split(b"\0"):
        k, sep, v = item.decode(errors="replace").partition("=")
        if sep:
            env[k] = v
    if not env.get("QNX_HOST"):
        raise BuildError(f"{script} did not set QNX_HOST")
    return env


@dataclass
class BuildResult:
    ok: bool
    rc: int
    seconds: float
    log: Path
    parsed: ParsedLog

    @property
    def phase(self) -> str:
        return "ok" if self.ok else self.parsed.phase


def build_dir(port_dir: Path, arch: str = "x86_64") -> Path:
    return port_dir / ARCH_DIRS[arch] / "build"


def clean(port_dir: Path, arch: str = "x86_64") -> None:
    shutil.rmtree(build_dir(port_dir, arch), ignore_errors=True)


def run_make(port_dir: Path, src: Path, stage: Path, log: Path, *, arch: str = "x86_64",
             jobs: int = 8, testing: bool = True, env: dict[str, str] | None = None,
             keep_going: bool = True, timeout: float | None = None) -> BuildResult:
    """`make install` in ports/<name>/nto-<arch>/, the same command the port README gives."""
    env = env if env is not None else sdp_env()
    stage.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    make_args = f"-j {jobs}" + (" -k" if keep_going else "")
    cmd = ["make", "-C", str(port_dir / ARCH_DIRS[arch]), "install",
           f"BUILD_TESTING={'ON' if testing else 'OFF'}", f"QNX_PROJECT_ROOT={src}",
           f"INSTALL_ROOT_nto={stage}", "USE_INSTALL_ROOT=1", f"JLEVEL={jobs}",
           f"MAKE_ARGS={make_args}"]
    t0 = time.perf_counter()
    with open(log, "w", encoding="utf-8", errors="replace") as fh:
        fh.write("$ " + " ".join(cmd) + "\n")
        fh.flush()
        try:
            rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, env=env,
                                timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            rc = -1
            fh.write("\nportpilot: build timed out\n")
    secs = time.perf_counter() - t0
    parsed = parse(log.read_text(encoding="utf-8", errors="replace"))
    return BuildResult(ok=rc == 0, rc=rc, seconds=secs, log=log, parsed=parsed)
