from pathlib import Path

import pytest

from portpilot import deps
from portpilot.diagnostics import parse
from portpilot.port import _build_deps


def test_a_missing_test_framework_header_builds_its_official_port(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """libcoap's tests include <CUnit/CUnit.h>; build-files has a cunit port."""
    calls = []

    def fake(pkg: str, *a: object, **k: object) -> tuple[str, str]:
        calls.append(pkg)
        return "cunit", ""

    monkeypatch.setattr(deps, "ensure_port", fake)
    errs = parse("tests/testdriver.c:13:10: fatal error: CUnit/CUnit.h: No such file or "
                 "directory\n").errors
    built = _build_deps(errs, set(), tmp_path, {}, tmp_path, tmp_path, "x86_64", 4,
                        lambda s: None)
    assert calls == ["CUnit"]
    assert [(p, f.rule_id, f.path) for p, f in built] == [("cunit", "dep-official-port",
                                                            "CUnit")]
