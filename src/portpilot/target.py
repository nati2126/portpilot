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

from .qnxtests import TestResult, count_cases, parse_results, point_localhost

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
    raise TargetError(f"VM in {vm_dir} did not answer on SSH within {wait_s:.0f}s"
                      + boot_problem(vm_dir))


_BROKEN_DISK = ("No system file system", "Can't mount /system", "Can't mount /data")


def boot_problem(vm_dir: Path) -> str:
    """What the VM's serial log says went wrong at boot, with the fix, or ""."""
    try:
        log = (vm_dir / "output" / "qemu.out").read_text(errors="replace")
    except OSError:
        return ""
    if any(s in log for s in _BROKEN_DISK):
        return (f": QNX could not mount its file systems (see {vm_dir}/output/qemu.out). "
                "The disk image is damaged, usually because the VM was killed while writing. "
                f"Rebuild it (same options and SSH keys): cd {vm_dir} && "
                "mkqnximage --build=all --noprompt")
    if "Startup complete" in log and _bridge_without_dhcp():
        return (": QNX booted, but nothing on the virbr0 bridge hands out addresses (no "
                "dnsmasq). On WSL the bridge outlives a distro restart and libvirt then "
                "refuses to restart its network ('already in use by interface virbr0'). Fix: "
                "sudo ip link delete virbr0 && virsh -c qemu:///system net-start default")
    return ""


def _bridge_without_dhcp() -> bool:
    """virbr0 exists but libvirt's dnsmasq for it is not running."""
    if not Path("/sys/class/net/virbr0").exists():
        return False
    r = subprocess.run(["pgrep", "-f", "dnsmasq.*default.conf"], capture_output=True,
                       check=False)
    return r.returncode != 0


def vm_stop(vm_dir: Path, env: dict[str, str], target: Target | None = None) -> None:
    """Stop the VM; flush its disks first when it is reachable (killing qemu mid-write can
    damage the image)."""
    if target is not None:
        with contextlib.suppress(subprocess.TimeoutExpired):
            target.ssh("sync", timeout=20)
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
    aborted: bool = False  # the runner stopped because every program hung
    localhost: str = ""  # test arguments' localhost was pointed at this host

    def cases(self) -> tuple[int, int] | None:
        """(passed, total) test cases: a program's own count where it printed one, else
        the program counts as one case. None if no program printed a count."""
        if not any(r.cases for r in self.results):
            return None
        p = sum(r.cases[0] if r.cases else int(r.status == "PASS") for r in self.results)
        n = sum(r.cases[1] if r.cases else 1 for r in self.results)
        return p, n


def stage_libs(test_dir: Path, have: set[str]) -> list[Path]:
    """Shared libraries installed in the stage, such as dependencies built from official
    ports (libCatch2Main.so), that the tests need on the target. test_dir is
    <stage>/<arch>/usr/local/bin/<name>_tests; qnxtests.sh puts its own folder on
    LD_LIBRARY_PATH."""
    arch_root = test_dir.parents[3]
    out: list[Path] = []
    for d in ("lib", "usr/lib", "usr/local/lib"):
        for f in sorted((arch_root / d).glob("*.so*")) if (arch_root / d).is_dir() else ():
            if f.name not in have and (f.is_file() or f.is_symlink()):
                have.add(f.name)
                out.append(f)
    return out


def run_tests(target: Target, test_dir: Path, name: str, out_dir: Path, *,
              timeout_scale: float = 3, remote_root: str = "/data",
              timeout: float = 4 * 3600, localhost: str = "") -> TestRun:
    """Copy the test folder to the target and run qnxtests.sh there. With `localhost`,
    the tests' localhost arguments name that host instead (see point_localhost)."""
    if not (test_dir / "qnxtests.sh").is_file():
        raise TargetError(f"{test_dir}/qnxtests.sh not found: build with tests first")
    remote = f"{remote_root}/{name}"
    r = target.ssh(f"rm -rf {remote}; mkdir -p {remote}")
    if r.returncode != 0:
        raise TargetError(f"cannot create {remote} on {target.host}: {r.stdout}{r.stderr}")
    files = sorted(test_dir.iterdir())
    files += stage_libs(test_dir, {f.name for f in files})
    out_dir.mkdir(parents=True, exist_ok=True)
    if localhost:
        if localhost == "host":
            localhost = host_address(target.host)
        runner = out_dir / "qnxtests.sh"
        runner.write_text(point_localhost((test_dir / "qnxtests.sh").read_text(), localhost),
                          newline="\n")
        files = [runner if f.name == "qnxtests.sh" else f for f in files]
    target.scp_to(files, remote + "/")
    # check the copy really landed (a full /data fails silently otherwise)
    n_local = len(files)
    r = target.ssh(f"ls {remote} | wc -l")
    if r.returncode != 0 or int((r.stdout.strip() or "0").split()[0]) < n_local:
        df = target.ssh(f"df -h {remote_root}").stdout
        raise TargetError(f"copy to {remote} incomplete (disk full?)\n{df}")
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
    for res in results:  # gtest/Catch2/...: count the cases inside each program
        log = logs / f"{res.name}.out"
        if log.is_file() and (c := count_cases(log.read_text(errors="replace"))):
            res.cases = list(c)
    passed = sum(r.status == "PASS" for r in results)
    tmo = sum(r.status == "TIMEOUT" for r in results)
    failed = len(results) - passed
    return TestRun(host=target.host, ok=summary is not None and failed == 0 and passed > 0,
                   passed=passed, failed=failed, timeouts=tmo, total=len(results),
                   seconds=round(secs, 1), results=results, output=str(out),
                   logs_dir=str(logs), finished=summary is not None,
                   aborted="QNXTEST-ABORT" in text, localhost=localhost)


def host_address(target_host: str) -> str:
    """This machine's address as the target sees it: the source address of the route to
    the target (a UDP connect sends no packet)."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((target_host, 9))
        return str(s.getsockname()[0])


def default_key() -> str:
    for k in ("~/.ssh/qnx_vm_ed25519", "~/.ssh/id_ed25519", "~/.ssh/id_rsa"):
        p = os.path.expanduser(k)
        if os.path.exists(p):
            return p
    return ""
