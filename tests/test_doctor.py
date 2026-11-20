"""portpilot doctor: required checks decide the exit code; target and AI are optional."""

from __future__ import annotations

from pathlib import Path

from portpilot.doctor import Check, check_sdp, render


def test_required_failure_sets_exit_code_and_prints_fix() -> None:
    text, rc = render([Check("qcc for x86_64", False, "not working", "source qnxsdp-env.sh"),
                       Check("git (clones)", True, "/usr/bin/git")])
    assert rc == 1
    assert "[FAIL] qcc for x86_64: not working\n       fix: source qnxsdp-env.sh" in text
    assert "1 required check(s) failed" in text


def test_optional_failures_still_ready_without_tests_or_ai() -> None:
    text, rc = render([Check("git", True, "/usr/bin/git"),
                       Check("mkqnximage (QEMU target image)", False, "not found", "x",
                             required=False),
                       Check("local model for --ai (m)", False, "no endpoint", "y",
                             required=False)])
    assert rc == 0
    assert "ready to port: portpilot port <github url> -o <dir> --no-tests" in text
    assert "the rules work without it" in text


def test_sdp_missing(tmp_path: Path) -> None:
    checks = check_sdp({"PATH": str(tmp_path)})
    assert [c.ok for c in checks] == [False, False, False]
    assert all("qnxsdp-env.sh" in c.fix for c in checks)
