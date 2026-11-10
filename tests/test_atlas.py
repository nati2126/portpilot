"""Atlas tiers and aggregation (synthetic records), and the VM boot-problem hint."""

from __future__ import annotations

from pathlib import Path

import pytest

from portpilot.atlas import aggregate, tier, to_markdown
from portpilot.target import boot_problem


def need(rule: str, fix: str, severity: str = "fix", count: int = 1) -> dict[str, object]:
    return {"rule": rule, "title": rule, "severity": severity, "fix": fix, "count": count,
            "where": []}


def rec(repo: str, needs: list[dict[str, object]], stars: int = 1000,
        markets: list[str] | None = None) -> dict[str, object]:
    return {"repo": repo, "stars": stars, "markets": markets or [], "needs": needs,
            "tier": tier(needs)}  # type: ignore[arg-type]


def test_tiers() -> None:
    assert tier([]) == "auto"
    assert tier([need("link-socket", "rule")]) == "auto"
    assert tier([need("link-socket", "rule"), need("dirent-d-type", "assisted")]) == "assisted"
    assert tier([need("epoll", "manual", "blocker"), need("dirent-d-type", "assisted")]) == \
        "redesign"
    assert tier([need("epoll", "manual", "info")]) == "auto"  # info never blocks
    deps = [need("third-party-dep", "manual", "blocker"), need("link-socket", "rule")]
    assert tier(deps) == "deps"
    assert tier([need("third-party-dep", "manual", "blocker"),
                 need("epoll", "manual", "blocker")]) == "redesign"
    assert tier([need("proc-fs", "manual", "warn")]) == "assisted"


def test_aggregate_ranks_blockers_and_sole_blockers() -> None:
    recs = [rec("a/net", [need("epoll", "manual", "blocker"), need("link-socket", "rule")],
                markets=["messaging"]),
            rec("b/ev", [need("epoll", "manual", "blocker")]),
            rec("c/fs", [need("epoll", "manual", "blocker"), need("inotify", "manual", "blocker")]),
            rec("d/ok", [need("link-socket", "rule")], stars=5000),
            {"repo": "e/broken", "stars": 1, "error": "clone failed"}]
    at = aggregate(recs)  # type: ignore[arg-type]
    assert (at["scanned"], at["analyzed"], at["errors"]) == (5, 4, 1)
    assert at["tiers"] == {"auto": 1, "assisted": 0, "deps": 0, "redesign": 3}
    top = at["blockers"][0]
    assert (top["rule"], top["libraries"], top["share"]) == ("epoll", 3, 0.75)
    assert top["sole_blocker_of"] == 2  # a/net and b/ev; c/fs also needs inotify
    assert at["markets"]["messaging"] == {"redesign": 1}
    assert at["libraries"][0]["repo"] == "d/ok"  # auto first
    md = to_markdown(at)
    assert "| auto (rules fix everything) | 1 | 25% |" in md
    assert "| epoll (`epoll`) | 3 | 75% | 2 | manual |" in md


def test_boot_problem_names_the_fix(tmp_path: Path) -> None:
    assert boot_problem(tmp_path) == ""
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "qemu.out").write_text(
        "mount: Can't mount /system (type qnx6)\nNo system file system, giving up.\n")
    hint = boot_problem(tmp_path)
    assert "disk image is damaged" in hint and "mkqnximage --build=all" in hint


def test_vm_network_is_restarted_when_libvirt_reports_it_down(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    from portpilot import target

    calls: list[list[str]] = []
    state = {"active": "no", "start_rc": 0}

    def run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if "net-info" in cmd:
            return subprocess.CompletedProcess(cmd, 0, f"Name: default\nActive:         "
                                               f"{state['active']}\n", "")
        if "net-start" in cmd:
            return subprocess.CompletedProcess(cmd, state["start_rc"], "", "error: Network "
                                               "is already in use by interface virbr0")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(target.shutil, "which", lambda *_a, **_k: "/usr/bin/virsh")
    monkeypatch.setattr(target.subprocess, "run", run)
    monkeypatch.setattr(target, "vm_running", lambda: True)
    assert "restarted" in target.ensure_vm_network(tmp_path, {})
    assert ["mkqnximage", "--stop", "--noprompt"] in calls  # off the old bridge first
    assert calls[-1][-2:] == ["net-start", "default"]
    state["start_rc"] = 1
    with pytest.raises(target.TargetError, match="sudo ip link delete virbr0"):
        target.ensure_vm_network(tmp_path, {})
    state["active"] = "yes"
    calls.clear()
    assert target.ensure_vm_network(tmp_path, {}) == "" and len(calls) == 1


def test_most_wanted_dependencies_and_official_ports() -> None:
    from portpilot.atlas import dependencies, package_of

    assert package_of("boost/asio.hpp") == "boost" and package_of("zmq.h") == "zmq"

    def dep(*names: str) -> dict[str, object]:
        return {**need("third-party-dep", "manual", "blocker"), "names": list(names)}

    recs = [rec("a/x", [dep("boost/asio.hpp", "boost/any.hpp")]),
            rec("b/y", [dep("boost/asio.hpp", "gtest/gtest.h")]),
            rec("c/z", [dep("rocksdb/db.h")]),
            rec("d/w", [dep("rocksdb/db.h"), need("epoll", "manual", "blocker")])]
    d = dependencies(recs, {"boost", "googletest"})  # type: ignore[arg-type]
    rows = {e["package"]: e for e in d["packages"]}
    assert rows["boost"]["libraries"] == 2 and rows["boost"]["qnx_port"]
    assert rows["gtest"]["qnx_port"]  # include folder gtest -> port googletest
    assert rows["rocksdb"] == {"package": "rocksdb", "libraries": 2, "sole_dependency_of": 1,
                               "qnx_port": False}  # d/w is redesign, not deps
    assert d["deps_tier_all_ported"] == 2  # a/x and b/y only need ported libraries
    md = to_markdown(aggregate(recs, {"boost", "googletest"}))  # type: ignore[arg-type]
    assert "| `rocksdb` | 2 | 1 | **no** |" in md
    assert "3 libraries blocked only by missing dependencies, 2 need only" in md
