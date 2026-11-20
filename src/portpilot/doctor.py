"""`portpilot doctor`: check that this machine can build, test and (optionally) AI-fix ports.

Each check says what it found and, when something is missing, the one thing to do about it.
Required checks decide the exit code; the QNX target and the local model are optional
(`port --no-tests` and running without `--ai` work without them).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass
class Check:
    name: str
    ok: bool
    found: str
    fix: str = ""
    required: bool = True


def _run(cmd: list[str], env: dict[str, str] | None = None) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20, env=env)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (r.stdout or r.stderr).strip() if r.returncode == 0 else ""


def check_python() -> Check:
    v = sys.version_info
    return Check("Python 3.11+", v >= (3, 11), f"{v.major}.{v.minor}.{v.micro}",
                 "install Python 3.11 or newer")


def check_tool(name: str, why: str, fix: str) -> Check:
    path = shutil.which(name)
    return Check(f"{name} ({why})", path is not None, path or "not found", fix)


def check_sdp(env: dict[str, str]) -> list[Check]:
    qt, qh = env.get("QNX_TARGET", ""), env.get("QNX_HOST", "")
    source = "source ~/qnx800/qnxsdp-env.sh (your QNX SDP 8.0 install)"
    out = [Check("QNX SDP environment", bool(qt and qh and Path(qt).is_dir()),
                 qt or "QNX_TARGET not set", source)]
    out.append(check_qcc(env, source))
    out.append(Check("QNX 8.0 headers", (Path(qt) / "usr/include/sys/neutrino.h").is_file()
                     if qt else False, f"{qt}/usr/include" if qt else "-", source))
    return out


def check_qcc(env: dict[str, str], fix: str) -> Check:
    """Compile a one-line program with qcc for x86_64. (qcc swallows -dumpversion, so the
    version comes from the target list `qcc -V` prints, e.g. '12.2.0,gcc_ntox86_64'.)"""
    qcc = shutil.which("qcc", path=env.get("PATH"))
    if qcc is None:
        return Check("qcc for x86_64", False, "not found", fix)
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "t.c"
        src.write_text("int main(void) { return 0; }\n")
        r = subprocess.run([qcc, "-Vgcc_ntox86_64", "-o", str(Path(d) / "t"), str(src)],
                           capture_output=True, text=True, env=env, timeout=60, check=False)
    if r.returncode != 0:
        return Check("qcc for x86_64", False, f"cannot compile: {r.stderr.strip()[:120]}", fix)
    vlist = subprocess.run([qcc, "-V"], capture_output=True, text=True, env=env, timeout=20,
                           check=False)
    m = re.search(r"([\d.]+),gcc_ntox86_64\b", vlist.stdout + vlist.stderr)
    return Check("qcc for x86_64", True, f"compiles (gcc {m.group(1)})" if m else "compiles")


def check_sdp_index(arch: str = "x86_64") -> Check:
    from .sdp_index import default_index_path

    p = default_index_path(arch)
    return Check("SDP index", p.is_file(), str(p) if p.is_file() else "not built",
                 "portpilot sdp-index   (once; reads your SDP, stays on this machine)")


def check_build_files(explicit: str | None = None) -> Check:
    from .deps import find_build_files

    bf = find_build_files(explicit)
    return Check("qnx-ports/build-files checkout", bf is not None, str(bf or "not found"),
                 "git clone https://github.com/qnx-ports/build-files ~/qnx-work/build-files"
                 "   (official ports used as dependencies)")


def check_target(vm: str | None, key: str | None, env: dict[str, str]) -> list[Check]:
    out = [Check("mkqnximage (QEMU target image)", shutil.which("mkqnximage", path=env.get(
        "PATH")) is not None, shutil.which("mkqnximage", path=env.get("PATH")) or "not found",
        "comes with the SDP: source qnxsdp-env.sh", required=False)]
    kvm = Path("/dev/kvm")
    out.append(Check("KVM", kvm.exists() and os.access(kvm, os.R_OK | os.W_OK),
                     "/dev/kvm usable" if kvm.exists() and os.access(kvm, os.W_OK)
                     else "no access (QEMU still works, slowly)",
                     "sudo usermod -aG kvm $USER, then log in again", required=False))
    k = Path(key or "~/.ssh/qnx_vm_ed25519").expanduser()
    out.append(Check("ssh key for the target", k.is_file(), str(k) if k.is_file() else
                     "not found", f'ssh-keygen -t ed25519 -N "" -f {k}', required=False))
    if vm:
        v = Path(vm).expanduser()
        img = v / "output"
        out.append(Check("QNX VM image", img.is_dir(), str(img) if img.is_dir() else
                         f"no image in {v}", f"cd {v} && mkqnximage --type=qemu --arch=x86_64 "
                         f"--ssh-ident={k}.pub", required=False))
    return out


def check_ai(url: str | None, model: str | None) -> Check:
    from . import ai

    p = ai.Provider(url or ai.DEFAULT_URL, model or ai.DEFAULT_MODEL, timeout=10)
    why = p.available()
    return Check(f"local model for --ai ({p.model})", not why, why or p.url,
                 f"install Ollama, then: ollama pull {p.model}", required=False)


def run_all(*, vm: str | None = None, key: str | None = None, build_files: str | None = None,
            ai_url: str | None = None, ai_model: str | None = None,
            env: dict[str, str] | None = None) -> list[Check]:
    env = dict(os.environ) if env is None else env
    return [check_python(),
            check_tool("cmake", "configures the ports", "sudo apt install cmake"),
            check_tool("make", "drives the build-files Makefiles", "sudo apt install make"),
            check_tool("git", "clones libraries and ports", "sudo apt install git"),
            replace(check_tool("autoreconf", "official ports that use autotools, e.g. cunit",
                               "sudo apt install autoconf automake libtool"), required=False),
            *check_sdp(env), check_sdp_index(), check_build_files(build_files),
            *check_target(vm, key, env), check_ai(ai_url, ai_model)]


def render(checks: list[Check]) -> tuple[str, int]:
    lines = []
    for c in checks:
        mark = "ok  " if c.ok else ("FAIL" if c.required else "--  ")
        lines.append(f"[{mark}] {c.name}: {c.found}")
        if not c.ok and c.fix:
            lines.append(f"       fix: {c.fix}")
    bad = [c for c in checks if c.required and not c.ok]
    opt = [c for c in checks if not c.required and not c.ok]
    lines.append("")
    if bad:
        lines.append(f"{len(bad)} required check(s) failed: portpilot cannot build ports yet.")
    else:
        lines.append("ready to port: portpilot port <github url> -o <dir>"
                     + (" --no-tests" if any("target" in c.name or "VM" in c.name
                                              or "mkqnximage" in c.name for c in opt) else ""))
        if any(c.name.startswith("local model") for c in opt):
            lines.append("(without --ai: no local model found; the rules work without it)")
    return "\n".join(lines), 1 if bad else 0
