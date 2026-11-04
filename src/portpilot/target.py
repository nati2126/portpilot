"""Run a port's tests on a QNX target over SSH (a QEMU VM made with mkqnximage, or a board).

The target needs only sshd and /bin/sh: we copy <stage>/<arch>/usr/local/bin/<name>_tests/
(test binaries, shared libraries and qnxtests.sh) to /data/<name>/ and run qnxtests.sh.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .qnxtests import TestResult, parse_results

_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


class TargetError(RuntimeError):
    pass


@dataclass
class Target:
    host: str
    user: str = "root"
    key: str = ""  # ssh identity file
    known_hosts: str = ""
    port: int = 22

    def _opts(self) -> list[str]:
        o = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "LogLevel=ERROR",
             "-o", "ServerAliveInterval=30", "-o", "StrictHostKeyChecking=accept-new"]
        if self.key:
            o += ["-i", self.key]
        if self.known_hosts:
            o += ["-o", f"UserKnownHostsFile={self.known_hosts}"]
        return o

    def ssh(self, command: str, *, timeout: float | None = 60, out: Path | None = None
            ) -> subprocess.CompletedProcess[str]:
        cmd = ["ssh", *self._opts(), "-p", str(self.port), f"{self.user}@{self.host}", command]
        if out is None:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                  stdin=subprocess.DEVNULL)
        with open(out, "w", encoding="utf-8", errors="replace") as fh:
            r = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, text=True,
                               timeout=timeout, stdin=subprocess.DEVNULL)
        return subprocess.CompletedProcess(cmd, r.returncode, out.read_text(errors="replace"), "")

    def scp_to(self, files: list[Path], dest: str, timeout: float = 600) -> None:
        cmd = ["scp", *self._opts(), "-q", "-r", "-P", str(self.port), *map(str, files),
               f"{self.user}@{self.host}:{dest}"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            raise TargetError(f"scp failed: {r.stderr.strip() or r.returncode}")

    def scp_from(self, src: str, dest: Path, timeout: float = 300) -> bool:
        cmd = ["scp", *self._opts(), "-q", "-r", "-P", str(self.port),
               f"{self.user}@{self.host}:{src}", str(dest)]
        return subprocess.run(cmd, capture_output=True, timeout=timeout,
                              stdin=subprocess.DEVNULL).returncode == 0

    def reachable(self) -> bool:
        try:
            return self.ssh("true", timeout=15).returncode == 0
        except subprocess.TimeoutExpired:
            return False


# ---- QEMU VM made with mkqnximage ------------------------------------------------------------
def vm_running() -> bool:
    """A mkqnximage QEMU VM runs as qemu with output/disk-qemu.* as its disk."""
    return subprocess.run(["pgrep", "-f", "disk-qemu"], capture_output=True).returncode == 0


def vm_ip(vm_dir: Path, env: dict[str, str]) -> str:
    """The VM's address, or "" (mkqnximage --getip blocks while the VM has no lease)."""
    if not vm_running():
        return ""
    try:
        r = subprocess.run(["mkqnximage", "--getip", "--noprompt"], cwd=vm_dir, env=env,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           timeout=20)
    except subprocess.TimeoutExpired:
        return ""
    m = _IP.search(r.stdout)
    return m.group(0) if m else ""


def vm_start(vm_dir: Path, env: dict[str, str], key: str = "", known_hosts: str = "",
             wait_s: float = 120) -> Target:
    """Boot the VM in vm_dir (if needed) and wait until SSH answers."""
    if shutil.which("mkqnximage", path=env.get("PATH")) is None:
        raise TargetError("mkqnximage not found: source qnxsdp-env.sh")
    if not vm_running():
        log = vm_dir / "output" / "portpilot-run.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        # never pipe mkqnximage --run: the background qemu keeps the pipe open
        with open(log, "w") as fh:
            subprocess.run(["mkqnximage", "--run=-h", "--noprompt"], cwd=vm_dir, env=env,
                           stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                           timeout=120)
    t_end = time.monotonic() + wait_s
    while time.monotonic() < t_end:
        ip = vm_ip(vm_dir, env)
        if ip:
            t = Target(ip, key=key, known_hosts=known_hosts)
            if t.reachable():
                return t
        time.sleep(3)
    raise TargetError(f"VM in {vm_dir} did not answer on SSH within {wait_s:.0f}s")


def vm_stop(vm_dir: Path, env: dict[str, str]) -> None:
    subprocess.run(["mkqnximage", "--stop", "--noprompt"], cwd=vm_dir, env=env,
                   capture_output=True, stdin=subprocess.DEVNULL, timeout=60)


# ---- deploy + run -----------------------------------------------------------------------------
@dataclass
class TestRun:
    host: str
    ok: bool
    passed: int
    failed: int
    timeouts: int
    total: int
    seconds: float
    results: list[TestResult] = field(default_factory=list)
    output: str = ""  # local file with the runner's output
    logs_dir: str = ""  # local copy of the per-test logs
    finished: bool = True


def run_tests(target: Target, test_dir: Path, name: str, out_dir: Path, *,
              timeout_scale: float = 3, remote_root: str = "/data",
              timeout: float = 4 * 3600) -> TestRun:
    if not (test_dir / "qnxtests.sh").is_file():
        raise TargetError(f"{test_dir}/qnxtests.sh not found: build with tests first")
    remote = f"{remote_root}/{name}"
    r = target.ssh(f"rm -rf {remote}; mkdir -p {remote}")
    if r.returncode != 0:
        raise TargetError(f"cannot create {remote} on {target.host}: {r.stdout}{r.stderr}")
    target.scp_to(sorted(test_dir.iterdir()), remote + "/")
    # check the copy really landed (a full /data fails silently otherwise)
    n_local = sum(1 for _ in test_dir.iterdir())
    r = target.ssh(f"ls {remote} | wc -l")
    if r.returncode != 0 or int((r.stdout.strip() or "0").split()[0]) < n_local:
        df = target.ssh(f"df -h {remote_root}").stdout
        raise TargetError(f"copy to {remote} incomplete (disk full?)\n{df}")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "qnxtests.out"
    scale = f"{timeout_scale:g}"
    t0 = time.perf_counter()
    with contextlib.suppress(subprocess.TimeoutExpired):
        target.ssh(f"TIMEOUT_SCALE={scale} sh {remote}/qnxtests.sh", timeout=timeout, out=out)
    secs = time.perf_counter() - t0
    text = out.read_text(errors="replace") if out.exists() else ""
    results, summary = parse_results(text)
    logs = out_dir / "target-logs"
    if logs.exists():
        shutil.rmtree(logs)
    target.scp_from(f"{remote}/logs", logs)
    passed = sum(r.status == "PASS" for r in results)
    tmo = sum(r.status == "TIMEOUT" for r in results)
    failed = len(results) - passed
    return TestRun(host=target.host, ok=summary is not None and failed == 0 and passed > 0,
                   passed=passed, failed=failed, timeouts=tmo, total=len(results),
                   seconds=round(secs, 1), results=results, output=str(out),
                   logs_dir=str(logs), finished=summary is not None)


def default_key() -> str:
    for k in ("~/.ssh/qnx_vm_ed25519", "~/.ssh/id_ed25519", "~/.ssh/id_rsa"):
        p = os.path.expanduser(k)
        if os.path.exists(p):
            return p
    return ""
