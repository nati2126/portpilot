"""Atlas tiers and aggregation (synthetic records), and the VM boot-problem hint."""

from __future__ import annotations

from pathlib import Path

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


def test_aggregate_ranks_blockers_and_sole_blockers() -> None:
    recs = [rec("a/net", [need("epoll", "manual", "blocker"), need("link-socket", "rule")],
                markets=["messaging"]),
            rec("b/ev", [need("epoll", "manual", "blocker")]),
            rec("c/fs", [need("epoll", "manual", "blocker"), need("inotify", "manual", "blocker")]),
            rec("d/ok", [need("link-socket", "rule")], stars=5000),
            {"repo": "e/broken", "stars": 1, "error": "clone failed"}]
    at = aggregate(recs)  # type: ignore[arg-type]
    assert (at["scanned"], at["analyzed"], at["errors"]) == (5, 4, 1)
    assert at["tiers"] == {"auto": 1, "assisted": 0, "redesign": 3}
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
